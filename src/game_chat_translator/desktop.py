from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from threading import Condition, Event, Lock, Thread, current_thread
from typing import Any
from uuid import UUID

from game_chat_translator.application import (
    ApplicationController,
    HistoryServices,
    ShutdownServices,
)
from game_chat_translator.capture.base import RawFrame
from game_chat_translator.core_runtime import CoreRuntime
from game_chat_translator.events import AppError, ErrorSeverity
from game_chat_translator.history import HistoryEntry, WindowGeometry
from game_chat_translator.learning import CandidateStatus, GlossaryLearner
from game_chat_translator.lifecycle import LifecycleState
from game_chat_translator.models import (
    ChatRegion,
    MessageClass,
    ReplyDraft,
    ReplyStatus,
    WindowIdentity,
)
from game_chat_translator.monitoring import LiveFrameSource, MonitoringWorker
from game_chat_translator.reply.audio import SoundDeviceAudioRecorder
from game_chat_translator.reply.clipboard import ClipboardDispatchBridge
from game_chat_translator.reply.coordinator import ReplyCoordinator, ReplyGenerations
from game_chat_translator.reply.faster_whisper_stt import IsolatedFasterWhisper
from game_chat_translator.reply.hotkeys import WindowsHoldKeyObserver, WindowsShortcutObserver
from game_chat_translator.reply.model_setup import (
    STT_MODEL_ID,
    SttModelSetup,
    SttSetupStatus,
)
from game_chat_translator.reply.targeting import SpeakerTracker
from game_chat_translator.resource_paths import bundled_resource_root
from game_chat_translator.settings import (
    AppSettings,
    SettingsError,
    SettingsStore,
)
from game_chat_translator.settings import (
    SpeechSettings as AppSpeechSettings,
)
from game_chat_translator.speech import (
    SpeechJob,
    SpeechOfferResult,
    SpeechSettings,
    SpeechWorker,
    WindowsSapiProvider,
)
from game_chat_translator.storage import HistoryRepository
from game_chat_translator.ui.dashboard import create_dashboard
from game_chat_translator.ui.event_queue import (
    PresentedMessage,
    UiEventKind,
    UiEventQueue,
    UiStatus,
)
from game_chat_translator.ui.single_instance import SingleInstanceGuard
from game_chat_translator.ui.translation_window import TranslationRow
from game_chat_translator.ui.tray import create_tray_icon
from game_chat_translator.vision.model_setup import OCR_MODEL_ID, OcrModelSetup, OcrSetupStatus

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def run_desktop_application(argv: list[str] | None = None) -> int:
    """Run the tray-first shell. Heavy/native imports stay behind this explicit boundary."""
    del argv
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    except ImportError:
        return 2

    application: Any = QApplication.instance() or QApplication([])
    application.setApplicationName("Game Chat Translator")
    application.setQuitOnLastWindowClosed(False)
    activation: dict[str, Any] = {"show": None, "pending": False}

    def activate_existing_window() -> None:
        show = activation.get("show")
        if callable(show):
            show()
        else:
            activation["pending"] = True

    instance_guard = SingleInstanceGuard(
        "GameChatTranslator.Desktop.v1",
        activate_existing_window,
    )
    if not instance_guard.is_primary:
        return 0

    degraded = False
    settings_store = SettingsStore()
    try:
        settings = settings_store.load()
    except SettingsError:
        settings = AppSettings()
        degraded = True

    ui_events = UiEventQueue()
    holder: dict[str, Any] = {}
    runtime_holder: dict[str, Any] = {
        "runtime": None,
        "history": None,
        "monitoring": None,
        "reply": None,
        "hold_key": None,
        "shortcuts": None,
    }
    storage_worker = _StorageWorker(
        on_failure=lambda code: _report_safe_error(holder, code, "storage")
    )
    background_tasks = _BackgroundTasks(
        on_failure=lambda code: _report_safe_error(holder, code, "application")
    )
    speech_worker = SpeechWorker(
        WindowsSapiProvider,
        settings=_speech_settings(settings),
        on_failure=lambda code: _report_safe_error(holder, code, "speech"),
    )

    def queue_speech(message: PresentedMessage) -> bool:
        if message.classification is not MessageClass.PLAYER_INBOUND:
            return True
        speaker = (message.speaker or "Player").strip() or "Player"
        text = _CONTROL_CHARACTERS.sub("", message.translated_text).strip()
        if not text:
            return True
        result = speech_worker.offer(SpeechJob(message.message_id, f"{speaker} said: {text}"))
        if result in {
            SpeechOfferResult.ACCEPTED,
            SpeechOfferResult.REJECTED_DUPLICATE,
            SpeechOfferResult.REJECTED_MUTED,
        }:
            return True
        if result is not SpeechOfferResult.REJECTED_FULL:
            _report_safe_error(holder, "SPEECH_BACKPRESSURE", "speech")
        return False

    history_services = _history_services(
        settings,
        runtime_holder,
        storage_worker,
    )
    ui_controller_holder: dict[str, DesktopUiController] = {}
    shutdown = ShutdownServices(
        stop_capture=lambda: _pause_monitoring(runtime_holder),
        close_compute=lambda: _close_compute(background_tasks, runtime_holder),
        close_speech=speech_worker.close,
        close_audio=lambda: _close_reply(runtime_holder),
        close_hotkeys=lambda: _close_hotkeys(runtime_holder),
        close_ui=lambda: ui_controller_holder["ui"].close_ui(),
        close_storage=lambda: _close_storage(storage_worker, runtime_holder),
    )
    controller = ApplicationController(
        settings,
        ui_events,
        shutdown=shutdown,
        history=history_services,
        queue_speech=queue_speech,
        set_speech_muted=speech_worker.set_muted,
    )
    holder["controller"] = controller
    if settings.reply.hold_to_talk.casefold() == "v":
        ui_events.publish_status(
            "hotkeys",
            "Hold-to-talk V may overlap a game control; the key is observed and never suppressed",
        )
    speech_worker.start()

    tray_available = bool(QSystemTrayIcon.isSystemTrayAvailable())
    ui_controller = DesktopUiController(
        controller,
        ui_events,
        application,
        storage_worker=storage_worker,
        history_repository=None,
        speech_worker=speech_worker,
        settings_store=settings_store,
        settings=settings,
        runtime=None,
        learner=None,
        background_tasks=background_tasks,
        runtime_holder=runtime_holder,
        calibrated=False,
    )
    ui_controller_holder["ui"] = ui_controller
    activation["show"] = ui_controller.show_dashboard
    dashboard: Any = create_dashboard(
        ui_controller,
        close_to_tray=settings.application.close_to_tray and tray_available,
        speech_rate=settings.speech.rate,
        speech_volume_percent=round(settings.speech.volume * 100),
        voices=(),
        selected_voice_id=settings.speech.voice_id,
        hotkeys=(
            ("Pause / Resume", settings.hotkeys.toggle_capture),
            ("Mute / Unmute", settings.hotkeys.toggle_speech),
            ("Clear History", settings.hotkeys.clear_history),
            ("Hold to Talk", settings.hotkeys.hold_to_talk),
        ),
        models=(),
        learned_terms=(),
        active_profile=settings.application.active_profile,
    )
    tray: Any = create_tray_icon(
        ui_controller,
        icon_path=str(bundled_resource_root() / "assets" / "app.ico"),
    )
    timer = QTimer()
    timer.setInterval(30)
    timer.timeout.connect(ui_controller.pump_events)
    ui_controller.bind(dashboard, tray, timer)
    if activation["pending"]:
        QTimer.singleShot(0, ui_controller.show_dashboard)
    shortcuts = WindowsShortcutObserver(
        {
            "toggle_pause": settings.hotkeys.toggle_capture,
            "toggle_mute": settings.hotkeys.toggle_speech,
            "clear_history": settings.hotkeys.clear_history,
        },
        ui_controller.queue_hotkey_action,
        on_failure=lambda code: _report_safe_error(holder, code, "hotkeys"),
    )
    runtime_holder["shortcuts"] = shortcuts
    shortcuts.start()
    background_tasks.submit(
        "speech-discovery",
        lambda cancelled: ui_controller.queue_voice_update(
            () if cancelled.is_set() else speech_worker.voices(timeout=2.0)
        ),
    )
    background_tasks.submit(
        "runtime-discovery",
        lambda cancelled: _discover_runtime(
            cancelled,
            settings,
            runtime_holder,
            ui_controller,
            controller,
            speech_worker,
            degraded,
        ),
    )

    controller.start(needs_setup=not degraded, degraded=degraded)
    timer.start()
    if tray_available:
        tray.show()
    dashboard.show()
    application.aboutToQuit.connect(ui_controller.quit_application)
    try:
        return int(application.exec())
    finally:
        controller.quit()
        instance_guard.close()


class DesktopUiController:
    """Qt-facing adapter. It owns views, while the application controller owns lifecycle."""

    def __init__(
        self,
        controller: ApplicationController,
        events: UiEventQueue,
        application: Any,
        *,
        storage_worker: _StorageWorker,
        history_repository: HistoryRepository | None,
        speech_worker: SpeechWorker,
        settings_store: SettingsStore,
        settings: AppSettings,
        runtime: CoreRuntime | None,
        learner: GlossaryLearner | None,
        background_tasks: _BackgroundTasks,
        runtime_holder: dict[str, Any],
        calibrated: bool,
    ) -> None:
        self._controller = controller
        self._events = events
        self._application = application
        self._storage_worker = storage_worker
        self._history_repository = history_repository
        self._speech_worker = speech_worker
        self._settings_store = settings_store
        self._settings = settings
        self._runtime = runtime
        self._learner = learner
        self._background_tasks = background_tasks
        self._runtime_holder = runtime_holder
        self._ui_thread = current_thread()
        self._ui_close_completed = Event()
        from PySide6.QtCore import QObject, Qt, Signal

        class _UiCloseBridge(QObject):
            requested = Signal()

        self._ui_close_bridge = _UiCloseBridge()
        self._ui_close_bridge.requested.connect(
            self._close_ui_on_ui_thread,
            Qt.ConnectionType.QueuedConnection,
        )
        self._dashboard: Any = None
        self._tray: Any = None
        self._timer: Any = None
        self._ui_closed = False
        self._calibration_lock = Lock()
        self._calibration_ready: tuple[WindowIdentity, RawFrame] | None = None
        self._calibration_failed = False
        self._calibration_handoff_failed = False
        self._calibrated = calibrated
        self._calibration_previous_state: LifecycleState | None = None
        self._pending_voices: tuple[tuple[str, str], ...] | None = None
        self._pending_runtime: (
            tuple[
                CoreRuntime,
                HistoryRepository,
                GlossaryLearner,
                bool,
                WindowGeometry | None,
                bool,
                tuple[tuple[str, str], ...],
                tuple[tuple[str, str, str], ...],
                MonitoringWorker | None,
                OcrModelSetup,
            ]
            | None
        ) = None
        self._pending_runtime_failed = False
        self._pending_monitoring_update: tuple[MonitoringWorker | None, str] | None = None
        self._monitoring: MonitoringWorker | None = None
        self._ocr_setup: OcrModelSetup | None = None
        self._pending_reply_draft: ReplyDraft | None = None
        self._pending_reply_copied = False
        self._clipboard = ClipboardDispatchBridge()
        self._pending_hotkey_actions: deque[str] = deque()

    def bind(self, dashboard: Any, tray: Any, timer: Any) -> None:
        self._dashboard = dashboard
        self._tray = tray
        self._timer = timer
        self._refresh_tray_state()

    def toggle_pause(self) -> None:
        state = self._controller.state
        if state in {LifecycleState.RECORDING_REPLY, LifecycleState.PROCESSING_REPLY}:
            self._runtime_holder["pause_after_reply"] = True
            reply = self._runtime_holder.get("reply")
            if isinstance(reply, ReplyCoordinator):
                reply.cancel(clear_draft=True)
            if self._monitoring is not None:
                self._monitoring.pause()
            self._safe_status("reply", "Voice reply cancelled; pausing monitoring")
            return
        if state is LifecycleState.MONITORING:
            self._controller.pause()
            if self._monitoring is not None:
                self._monitoring.pause()
        else:
            if self._monitoring is None:
                self._safe_status("monitoring", "Install the verified local OCR models first")
                return
            self._controller.resume()
            self._monitoring.resume()
        self._refresh_tray_state()

    def toggle_mute(self) -> None:
        self._controller.set_muted(not self._controller.muted)
        self._refresh_tray_state()

    def calibrate(self) -> None:
        if self._runtime is None:
            self._safe_status("calibration", "Calibration storage is unavailable")
            return
        with self._calibration_lock:
            if self._calibration_previous_state is not None:
                self._safe_status("calibration", "Calibration is already in progress")
                return
            self._calibration_previous_state = self._controller.state
        self._controller.pause()
        if self._monitoring is not None:
            self._monitoring.pause()
        self._refresh_tray_state()
        self._safe_status("calibration", "Switch to the game window; capture begins shortly")
        if self._tray is not None:
            self._tray.showMessage(
                "Chat area calibration",
                "Switch to the game window. A frozen client-area screenshot will be captured.",
            )
        if self._dashboard is not None:
            self._dashboard.hide()

        def capture(cancelled: Event) -> None:
            monitoring = self._monitoring
            if monitoring is not None and not monitoring.wait_paused(3):
                with self._calibration_lock:
                    self._calibration_failed = True
                return
            if cancelled.wait(1.5):
                return
            try:
                result = _capture_foreground_client()
            except Exception:
                with self._calibration_lock:
                    self._calibration_failed = True
                return
            with self._calibration_lock:
                self._calibration_ready = result

        self._background_tasks.submit("calibration-capture", capture)

    def clear_history(self) -> None:
        self._controller.clear_visible_history()
        reply = self._runtime_holder.get("reply")
        if isinstance(reply, ReplyCoordinator):
            reply.clear()
        if self._dashboard is not None:
            self._dashboard.clear_messages()

        def clear(_cancelled: Event) -> None:
            self._controller.clear_history_backing()
            self._safe_status("history", "History cleared")

        if not self._background_tasks.submit("clear-history", clear):
            self._safe_status("history", "History clearing is unavailable")

    def cancel_reply(self) -> None:
        reply = self._runtime_holder.get("reply")
        if isinstance(reply, ReplyCoordinator):
            reply.cancel(clear_draft=True)
        if self._dashboard is not None:
            self._dashboard.set_reply_draft(
                ReplyDraft(
                    transcript="",
                    target_speaker=None,
                    target_language=None,
                    translated_text=None,
                    confidence=0,
                    status=ReplyStatus.CANCELLED,
                )
            )

    def retry_reply(self, text: str) -> None:
        reply = self._runtime_holder.get("reply")
        if not isinstance(reply, ReplyCoordinator):
            self._safe_status("reply", "Voice reply is unavailable")
            return
        try:
            result = reply.retry_copy(text)
        except ValueError:
            self._safe_status("reply", "Enter a translated reply before copying")
            return
        if result.value != "accepted":
            self._safe_status("reply", "No editable reply is ready")

    def select_reply_target(self, speaker_id: str) -> None:
        reply = self._runtime_holder.get("reply")
        if not isinstance(reply, ReplyCoordinator):
            return
        try:
            identity = UUID(speaker_id)
        except ValueError:
            self._safe_status("reply", "Choose one exact recent speaker")
            return
        if reply.select_target(identity).value != "accepted":
            self._safe_status("reply", "The selected speaker is no longer available")

    def open_model_manager(self) -> None:
        self._safe_status("models", "Choose Download / Verify or Remove on the model page")

    def open_learned_terms(self) -> None:
        self._safe_status("learning", "Review pending terms on the Profiles page")

    def export_diagnostics(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        filename, _selected_filter = QFileDialog.getSaveFileName(
            self._dashboard,
            "Export privacy-redacted diagnostics",
            "game-chat-translator-debug-bundle.zip",
            "ZIP archive (*.zip)",
        )
        if not filename:
            return

        def export(_cancelled: Event) -> None:
            from game_chat_translator.diagnostics import export_debug_bundle

            export_debug_bundle(Path(filename))
            self._safe_status("diagnostics", "Diagnostics exported")

        self._background_tasks.submit("diagnostics", export)

    def download_model(self, model_id: str) -> None:
        runtime = self._runtime
        if runtime is None:
            self._safe_status("models", "Model management is unavailable")
            return

        if model_id == STT_MODEL_ID:
            setup = self._runtime_holder.get("stt_setup")
            if not isinstance(setup, SttModelSetup):
                self._safe_status("models", "Speech model setup is unavailable")
                return
            stt_setup = setup

            def install_stt(cancelled: Event) -> None:
                outcome = stt_setup.install(
                    cancelled=cancelled.is_set,
                    progress=lambda received, total: self._safe_status(
                        "models", f"Speech model download {received * 100 // total}%"
                    ),
                )
                self._safe_status("models", outcome.message)
                if outcome.status not in {SttSetupStatus.INSTALLED, SttSetupStatus.READY}:
                    return
                monitoring = self._monitoring
                speakers = self._runtime_holder.get("speakers")
                path = stt_setup.ready_path()
                if monitoring is None or not isinstance(speakers, SpeakerTracker) or path is None:
                    self._safe_status(
                        "models", "Start verified OCR monitoring before voice replies"
                    )
                    return
                _activate_reply_services(
                    self._runtime_holder,
                    monitoring,
                    speakers,
                    path,
                    self._controller,
                    self._speech_worker,
                    self,
                    self._settings,
                )
                self._safe_status("reply", "Hold-to-talk is ready")

            if not self._background_tasks.submit("stt-model-setup", install_stt):
                self._safe_status("models", "Speech model setup is already running")
            return

        if model_id == OCR_MODEL_ID:
            setup = self._ocr_setup
            if setup is None:
                self._safe_status("models", "OCR model setup is unavailable")
                return

            def install_ocr(cancelled: Event) -> None:
                with self._calibration_lock:
                    already_running = self._monitoring is not None
                if already_running:
                    self._safe_status("models", "OCR models are already active")
                    return
                outcome = setup.install(
                    cancelled=cancelled.is_set,
                    progress=lambda received, total: self._safe_status(
                        "models", f"OCR download {received * 100 // total}%"
                    ),
                )
                self._safe_status("models", outcome.message)
                if outcome.status not in {OcrSetupStatus.INSTALLED, OcrSetupStatus.READY}:
                    return
                speakers = self._runtime_holder.get("speakers")
                if not isinstance(speakers, SpeakerTracker):
                    speakers = SpeakerTracker()
                    self._runtime_holder["speakers"] = speakers
                monitoring = _build_monitoring(
                    runtime, self._controller, self._settings, setup, speakers
                )
                if monitoring is None:
                    self._safe_status("models", "OCR models did not pass runtime validation")
                    return
                stt_setup = self._runtime_holder.get("stt_setup")
                stt_path = stt_setup.ready_path() if isinstance(stt_setup, SttModelSetup) else None
                if stt_path is not None:
                    _activate_reply_services(
                        self._runtime_holder,
                        monitoring,
                        speakers,
                        stt_path,
                        self._controller,
                        self._speech_worker,
                        self,
                        self._settings,
                    )
                self.queue_monitoring_update(monitoring, "OCR models are ready")

            if not self._background_tasks.submit("ocr-model-setup", install_ocr):
                self._safe_status("models", "OCR model setup is already running")
            return

        def download(cancelled: Event) -> None:
            outcome = runtime.download_model(
                model_id,
                cancelled=cancelled.is_set,
                progress=lambda received, total: self._safe_status(
                    "models", f"download {received * 100 // total}%"
                ),
            )
            self._safe_status("models", outcome.message)

        self._background_tasks.submit(f"download:{model_id}", download)

    def remove_model(self, model_id: str) -> None:
        runtime = self._runtime
        if runtime is None:
            self._safe_status("models", "Model management is unavailable")
            return

        if model_id == STT_MODEL_ID:
            setup = self._runtime_holder.get("stt_setup")
            if not isinstance(setup, SttModelSetup):
                self._safe_status("models", "Speech model setup is unavailable")
                return
            stt_setup = setup

            def remove_stt(_cancelled: Event) -> None:
                _close_hold_key(self._runtime_holder)
                _close_reply(self._runtime_holder)
                outcome = stt_setup.remove(in_use=False)
                self._safe_status("models", outcome.message)

            if not self._background_tasks.submit("stt-model-remove", remove_stt):
                self._safe_status("models", "Speech model removal is already running")
            return

        if model_id == OCR_MODEL_ID:
            setup = self._ocr_setup
            if setup is None:
                self._safe_status("models", "OCR model setup is unavailable")
                return

            def remove_ocr(_cancelled: Event) -> None:
                _close_hold_key(self._runtime_holder)
                _close_reply(self._runtime_holder)
                with self._calibration_lock:
                    monitoring = self._monitoring
                if monitoring is not None:
                    monitoring.pause()
                    monitoring.close()
                outcome = setup.remove(in_use=False)
                self._safe_status("models", outcome.message)
                if outcome.status is OcrSetupStatus.REMOVED:
                    self.queue_monitoring_update(None, "OCR models were removed")

            if not self._background_tasks.submit("ocr-model-remove", remove_ocr):
                self._safe_status("models", "OCR model removal is already running")
            return

        def remove(_cancelled: Event) -> None:
            outcome = runtime.remove_model(model_id)
            self._safe_status("models", outcome.message)

        self._background_tasks.submit(f"remove:{model_id}", remove)

    def set_learned_term_status(self, alias: str, status: str) -> None:
        learner = self._learner
        if learner is None:
            self._safe_status("learning", "Learned terms are unavailable")
            return

        def update(_cancelled: Event) -> None:
            candidate = learner.set_status(alias, CandidateStatus(status))
            self._safe_status("learning", f"Term marked {candidate.status.value}")

        self._background_tasks.submit("learning-update", update)

    def open_licenses(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        notices = bundled_resource_root() / "THIRD_PARTY_NOTICES.md"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(notices)))

    def set_speech_rate(self, rate: int) -> None:
        speech = self._settings.speech.model_copy(update={"rate": rate})
        self._save_speech_settings(speech)

    def set_speech_volume(self, volume_percent: int) -> None:
        volume = max(0, min(100, volume_percent)) / 100
        speech = self._settings.speech.model_copy(update={"volume": volume})
        self._save_speech_settings(speech)

    def select_speech_voice(self, voice_id: str | None) -> None:
        speech = self._settings.speech.model_copy(update={"voice_id": voice_id})
        self._save_speech_settings(speech)

    def dashboard_hidden(self) -> None:
        self._safe_status("dashboard", "hidden")

    def show_dashboard(self) -> None:
        if self._dashboard is None:
            return
        self._dashboard.show()
        self._dashboard.raise_()
        self._dashboard.activateWindow()

    def quit_application(self) -> None:
        self._controller.quit()

    def translation_geometry_changed(
        self, geometry: tuple[int, int, int, int], display_id: str
    ) -> None:
        repository = self._history_repository
        if repository is None:
            return
        value = WindowGeometry(display_id, *geometry)
        self._storage_worker.submit_latest(
            "translation-geometry",
            lambda: repository.save_geometry(value),
        )

    def pump_events(self) -> None:
        with self._calibration_lock:
            voices = self._pending_voices
            self._pending_voices = None
            runtime_update = self._pending_runtime
            self._pending_runtime = None
            runtime_failed = self._pending_runtime_failed
            self._pending_runtime_failed = False
            monitoring_update = self._pending_monitoring_update
            self._pending_monitoring_update = None
            reply_draft = self._pending_reply_draft
            self._pending_reply_draft = None
            reply_copied = self._pending_reply_copied
            self._pending_reply_copied = False
            hotkey_actions = tuple(self._pending_hotkey_actions)
            self._pending_hotkey_actions.clear()
        for action in hotkey_actions:
            if action == "toggle_pause":
                self.toggle_pause()
            elif action == "toggle_mute":
                self.toggle_mute()
            elif action == "clear_history":
                self.clear_history()
        self._clipboard.process(self._copy_clipboard_on_ui_thread)
        if reply_draft is not None and self._dashboard is not None:
            self._dashboard.set_reply_draft(reply_draft)
            if reply_draft.status.value == "needs_target":
                speakers = self._runtime_holder.get("speakers")
                if isinstance(speakers, SpeakerTracker):
                    self._dashboard.set_reply_targets(
                        tuple(
                            (str(target.speaker_id), target.display_name)
                            for target in speakers.candidates()
                        )
                    )
        if reply_copied and self._tray is not None:
            self._tray.showMessage("Reply copied", "The translated reply is on your clipboard.")
        if voices is not None and self._dashboard is not None:
            self._dashboard.set_voices(voices, self._settings.speech.voice_id)
        if runtime_update is not None:
            (
                runtime,
                history,
                learner,
                calibrated,
                geometry,
                startup_degraded,
                models,
                learned_terms,
                monitoring,
                ocr_setup,
            ) = runtime_update
            self._runtime = runtime
            self._history_repository = history
            self._learner = learner
            self._monitoring = monitoring
            self._ocr_setup = ocr_setup
            self._calibrated = calibrated
            self._dashboard.set_models(models)
            self._dashboard.set_learned_terms(learned_terms)
            del geometry
            if startup_degraded:
                self._controller.restore_operational_state(LifecycleState.DEGRADED)
            elif calibrated and monitoring is not None:
                self._controller.resume()
                monitoring.resume()
            else:
                self._controller.restore_operational_state(LifecycleState.NEEDS_SETUP)
                if calibrated:
                    self._safe_status(
                        "monitoring", "Install the verified local OCR models to start monitoring"
                    )
            self._dashboard.set_setup_state(
                ocr_ready=monitoring is not None,
                calibrated=calibrated,
                monitoring=calibrated and monitoring is not None,
            )
            self._refresh_tray_state()
        if monitoring_update is not None:
            monitoring, monitoring_status = monitoring_update
            self._monitoring = monitoring
            self._runtime_holder["monitoring"] = monitoring
            if monitoring is not None and self._calibrated:
                self._controller.restore_operational_state(LifecycleState.MONITORING)
                monitoring.resume()
            else:
                self._controller.restore_operational_state(LifecycleState.NEEDS_SETUP)
            if self._dashboard is not None:
                self._dashboard.set_setup_state(
                    ocr_ready=monitoring is not None,
                    calibrated=self._calibrated,
                    monitoring=monitoring is not None and self._calibrated,
                )
            self._safe_status("monitoring", monitoring_status)
            self._refresh_tray_state()
        if runtime_failed:
            self._controller.restore_operational_state(LifecycleState.DEGRADED)
            self._safe_status("startup", "Local runtime storage could not be opened")
            self._refresh_tray_state()
        self._open_pending_calibration()
        for event in self._events.drain(maximum=128):
            if event.kind is UiEventKind.MESSAGE:
                message = event.payload
                assert isinstance(message, PresentedMessage)
                self._dashboard.append_translation(
                    TranslationRow(
                        str(message.message_id),
                        message.speaker or "Player",
                        message.translated_text,
                        message.source_text,
                    )
                )
            elif event.kind is UiEventKind.ERROR:
                error = event.payload
                assert isinstance(error, AppError)
                self._dashboard.set_status(error.user_message)
            else:
                status = event.payload
                assert isinstance(status, UiStatus)
                self._dashboard.set_status(f"{status.key}: {status.value}")

    def queue_voice_update(self, voices: tuple[tuple[str, str], ...]) -> None:
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_voices = voices

    def queue_runtime_update(
        self,
        runtime: CoreRuntime,
        history: HistoryRepository,
        learner: GlossaryLearner,
        *,
        calibrated: bool,
        geometry: WindowGeometry | None,
        startup_degraded: bool,
        models: tuple[tuple[str, str], ...],
        learned_terms: tuple[tuple[str, str, str], ...],
        monitoring: MonitoringWorker | None,
        ocr_setup: OcrModelSetup,
    ) -> None:
        with self._calibration_lock:
            if self._ui_closed:
                return
            self._pending_runtime = (
                runtime,
                history,
                learner,
                calibrated,
                geometry,
                startup_degraded,
                models,
                learned_terms,
                monitoring,
                ocr_setup,
            )

    def queue_monitoring_update(self, monitoring: MonitoringWorker | None, status: str) -> None:
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_monitoring_update = (monitoring, status)

    def queue_runtime_failure(self) -> None:
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_runtime_failed = True

    def queue_reply_draft(self, draft: ReplyDraft) -> None:
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_reply_draft = draft

    def queue_hotkey_action(self, action: str) -> None:
        if action not in {"toggle_pause", "toggle_mute", "clear_history"}:
            return
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_hotkey_actions.append(action)

    def queue_reply_copied(self) -> None:
        with self._calibration_lock:
            if not self._ui_closed:
                self._pending_reply_copied = True

    def copy_reply_to_clipboard(self, text: str, timeout: float = 5.0) -> bool:
        return self._clipboard.request_copy(text, timeout=timeout)

    def _copy_clipboard_on_ui_thread(self, text: str) -> bool:
        if self._ui_closed:
            return False
        clipboard = self._application.clipboard()
        clipboard.setText(text)
        return bool(clipboard.text() == text)

    def close_ui(self) -> None:
        if current_thread() is not self._ui_thread:
            self._ui_close_bridge.requested.emit()
            if not self._ui_close_completed.wait(5):
                raise RuntimeError("UI thread did not process the shutdown request")
            return
        self._close_ui_on_ui_thread()

    def _close_ui_on_ui_thread(self) -> None:
        if self._ui_closed:
            self._ui_close_completed.set()
            return
        self._ui_closed = True
        with self._calibration_lock:
            self._pending_reply_draft = None
            self._pending_hotkey_actions.clear()
        self._clipboard.close()
        if self._timer is not None:
            self._timer.stop()
        if self._tray is not None:
            self._tray.hide()
        if self._dashboard is not None:
            self._dashboard.hide()
        self._ui_close_completed.set()
        self._application.quit()

    def _safe_status(self, key: str, value: str) -> None:
        with suppress(Exception):
            self._events.publish_status(key, value)

    def _save_speech_settings(self, speech: AppSpeechSettings) -> None:
        self._settings = self._settings.model_copy(update={"speech": speech})
        self._controller.update_settings(self._settings)
        self._speech_worker.update_settings(_speech_settings(self._settings))
        settings = self._settings
        self._storage_worker.submit_latest(
            "settings",
            lambda: self._settings_store.save(settings),
        )

    def _open_pending_calibration(self) -> None:
        with self._calibration_lock:
            failed = self._calibration_failed
            ready = self._calibration_ready
            self._calibration_failed = False
            self._calibration_ready = None
        if failed:
            self._safe_status("calibration", "The game client could not be captured safely")
            self._finish_calibration(saved=False)
            self.show_dashboard()
        if ready is None:
            return
        window, frame = ready
        from game_chat_translator.detection.region_calibrator import (
            CalibrationMetadata,
            CalibrationSession,
        )
        from game_chat_translator.ui.region_selector import launch_region_selector

        repository = self._runtime.state_repository() if self._runtime is not None else None
        if repository is None:
            self.show_dashboard()
            return

        def request_save(region: ChatRegion, completed: Callable[[bool], None]) -> None:
            runtime = self._runtime
            assert runtime is not None

            def save(cancelled: Event) -> None:
                if cancelled.is_set():
                    completed(False)
                    return
                try:
                    _persist_calibration_after_generation_handoff(
                        runtime,
                        self._monitoring,
                        repository,
                        self._settings.application.active_profile,
                        window.monitor_id,
                        region,
                    )
                except _CalibrationHandoffError:
                    with self._calibration_lock:
                        self._calibration_handoff_failed = True
                    self._safe_status(
                        "calibration", "Chat area activation failed; monitoring remains stopped"
                    )
                    completed(False)
                    return
                except (OSError, RuntimeError, ValueError):
                    self._safe_status("calibration", "Chat area could not be saved")
                    completed(False)
                    return
                self._safe_status("calibration", "Chat area saved")
                completed(True)

            if not self._background_tasks.submit("calibration-save", save):
                completed(False)

        session = CalibrationSession(
            CalibrationMetadata(
                profile_id=self._settings.application.active_profile,
                layout_id="default",
                monitor_id=window.monitor_id,
                client_width=frame.width,
                client_height=frame.height,
                dpi=window.dpi,
            ),
            frame.pixels,
            persist=lambda _region: None,
        )

        def request_retry(completed: Callable[[bytes | None], None]) -> None:
            submitted = self._background_tasks.submit(
                "calibration-retry",
                lambda _cancelled: _complete_retry_capture(window, completed),
            )
            if not submitted:
                completed(None)

        try:
            self._safe_status(
                "calibration",
                "OCR preview is unavailable; saving requires explicit confirmation",
            )
            launch_region_selector(
                session,
                request_retry=request_retry,
                request_preview=lambda _frame, completed: completed(False, ()),
                request_save=request_save,
                on_finished=self._finish_calibration,
            )
        except (OSError, RuntimeError, ValueError):
            self._safe_status("calibration", "Calibration could not be opened")
            self._finish_calibration(saved=False)

    def _finish_calibration(self, saved: bool) -> None:
        with self._calibration_lock:
            previous = self._calibration_previous_state
            self._calibration_previous_state = None
            handoff_failed = self._calibration_handoff_failed
            self._calibration_handoff_failed = False
        if previous is None:
            return
        if saved:
            self._calibrated = True
        target = (
            LifecycleState.DEGRADED
            if handoff_failed
            else _calibration_restore_target(previous, saved=saved)
        )
        self._controller.restore_operational_state(target)
        if self._monitoring is not None and target is LifecycleState.MONITORING:
            self._monitoring.resume()
        self._refresh_tray_state()
        self.show_dashboard()

    def _refresh_tray_state(self) -> None:
        if self._tray is None:
            return
        self._tray.set_runtime_state(
            profile_id=self._settings.application.active_profile,
            calibrated=self._calibrated,
            paused=self._controller.state is not LifecycleState.MONITORING,
            muted=self._controller.muted,
        )


class _StorageWorker:
    def __init__(self, *, on_failure: Callable[[str], None]) -> None:
        self._on_failure = on_failure
        self._lossless: deque[tuple[Callable[[], object], Event | None]] = deque()
        self._latest: dict[str, Callable[[], object]] = {}
        self._condition = Condition()
        self._closed = False
        self._thread = Thread(target=self._run, name="gct-storage", daemon=True)
        self._thread.start()

    def submit(self, callback: Callable[[], object], *, wait: bool) -> None:
        completed = Event() if wait else None
        with self._condition:
            if self._closed:
                raise RuntimeError("storage worker is closed")
            while len(self._lossless) >= 64 and not self._closed:
                self._condition.wait()
            if self._closed:
                raise RuntimeError("storage worker is closed")
            self._lossless.append((callback, completed))
            self._condition.notify_all()
        if completed is not None and not completed.wait(5):
            raise RuntimeError("storage operation timed out")

    def submit_latest(self, key: str, callback: Callable[[], object]) -> None:
        with self._condition:
            if self._closed:
                return
            self._latest[key] = callback
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._thread.join(5)
        if self._thread.is_alive():
            raise RuntimeError("storage worker did not stop")

    def _run(self) -> None:
        while True:
            completed: Event | None = None
            with self._condition:
                while not self._lossless and not self._latest and not self._closed:
                    self._condition.wait()
                if self._lossless:
                    callback, completed = self._lossless.popleft()
                    self._condition.notify_all()
                elif self._latest:
                    key = next(iter(self._latest))
                    callback = self._latest.pop(key)
                elif self._closed:
                    return
                else:
                    continue
            try:
                callback()
            except Exception:
                self._on_failure("STORAGE_OPERATION_FAILED")
            finally:
                if completed is not None:
                    completed.set()


class _BackgroundTasks:
    """Own cancellable setup/export tasks without running providers or I/O on the UI thread."""

    def __init__(self, *, on_failure: Callable[[str], None]) -> None:
        self._on_failure = on_failure
        self._cancelled = Event()
        self._threads: set[Thread] = set()
        self._lock = Lock()
        self._closed = False

    def submit(self, name: str, work: Callable[[Event], None]) -> bool:
        with self._lock:
            if self._closed:
                return False

            def run() -> None:
                try:
                    work(self._cancelled)
                except Exception:
                    self._on_failure("BACKGROUND_TASK_FAILED")
                finally:
                    with self._lock:
                        self._threads.discard(current_thread())

            thread = Thread(target=run, name=f"gct-{name}", daemon=True)
            self._threads.add(thread)
            thread.start()
            return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancelled.set()
            threads = tuple(self._threads)
        for thread in threads:
            thread.join(10)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("background application tasks did not stop")


def _history_services(
    settings: AppSettings,
    runtime_holder: dict[str, Any],
    worker: _StorageWorker,
) -> HistoryServices:
    def persist(message: PresentedMessage, retention_days: int) -> None:
        repository = runtime_holder.get("history")
        if not isinstance(repository, HistoryRepository):
            raise RuntimeError("history repository is not ready")
        entry = HistoryEntry(
            str(message.message_id),
            message.created_at.astimezone(UTC),
            settings.application.active_profile,
            message.speaker,
            message.source_text,
            message.translated_text,
            "unknown",
            settings.translation.target,
        )
        worker.submit(
            lambda: repository.append(
                entry,
                persistence_enabled=True,
                retention_days=retention_days,
            ),
            wait=True,
        )

    def clear_translation_cache() -> None:
        runtime = runtime_holder.get("runtime")
        if isinstance(runtime, CoreRuntime):
            runtime.clear_translation_history()

    def clear_persisted() -> None:
        repository = runtime_holder.get("history")
        if isinstance(repository, HistoryRepository):
            worker.submit(repository.clear, wait=True)

    return HistoryServices(
        persist=persist,
        clear_translation_cache=clear_translation_cache,
        clear_persisted=clear_persisted,
    )


def _discover_runtime(
    cancelled: Event,
    settings: AppSettings,
    runtime_holder: dict[str, Any],
    ui_controller: DesktopUiController,
    controller: ApplicationController,
    speech_worker: SpeechWorker,
    startup_degraded: bool,
) -> None:
    if cancelled.is_set():
        return
    runtime: CoreRuntime | None = None
    try:
        runtime = CoreRuntime()
        history = runtime.history_repository()
        history.purge_expired()
        learner = runtime.glossary_learner(settings.application.active_profile)
        calibrated = runtime.state_repository().has_calibration(settings.application.active_profile)
        geometry = history.load_latest_geometry()
        from game_chat_translator.settings import default_data_dir

        ocr_setup = OcrModelSetup(default_data_dir() / "models" / "ocr")
        stt_setup = SttModelSetup(default_data_dir() / "models" / "speech")
        ocr_state = "Ready" if ocr_setup.ready_paths() is not None else "Required — not installed"
        stt_state = "Ready" if stt_setup.ready_path() is not None else "Optional — not installed"
        models = (
            (
                OCR_MODEL_ID,
                "PaddleOCR v5 detection + Cyrillic recognition — "
                f"{ocr_setup.size_bytes / 1024**2:.1f} MiB — Apache-2.0 — {ocr_state}",
            ),
            (
                STT_MODEL_ID,
                "faster-whisper small.en — "
                f"{stt_setup.size_bytes / 1024**2:.1f} MiB — MIT — {stt_state}",
            ),
            *(
                (
                    entry.model_id,
                    f"{entry.model_id} — {entry.size_bytes / 1024**3:.1f} GiB — "
                    f"{entry.license_id} — Optional local translation",
                )
                for entry in runtime.manifest_entries
            ),
        )
        learned_terms = tuple(
            (
                candidate.display_alias,
                candidate.proposed_canonical,
                candidate.status.value,
            )
            for candidate in learner.list_candidates()
        )
        speakers = SpeakerTracker()
        monitoring = _build_monitoring(runtime, controller, settings, ocr_setup, speakers)
        if cancelled.is_set():
            runtime.close()
            return
        runtime_holder["runtime"] = runtime
        runtime_holder["history"] = history
        runtime_holder["monitoring"] = monitoring
        runtime_holder["speakers"] = speakers
        runtime_holder["stt_setup"] = stt_setup
        stt_path = stt_setup.ready_path()
        if monitoring is not None and stt_path is not None:
            _activate_reply_services(
                runtime_holder,
                monitoring,
                speakers,
                stt_path,
                controller,
                speech_worker,
                ui_controller,
                settings,
            )
        ui_controller.queue_runtime_update(
            runtime,
            history,
            learner,
            calibrated=calibrated,
            geometry=geometry,
            startup_degraded=startup_degraded,
            models=models,
            learned_terms=learned_terms,
            monitoring=monitoring,
            ocr_setup=ocr_setup,
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        if runtime is not None:
            runtime.close()
        ui_controller.queue_runtime_failure()


def _build_monitoring(
    runtime: CoreRuntime,
    controller: ApplicationController,
    settings: AppSettings,
    ocr_setup: OcrModelSetup,
    speakers: SpeakerTracker | None = None,
) -> MonitoringWorker | None:
    from game_chat_translator.application import InboundPresentationService
    from game_chat_translator.application_pipeline import ApplicationPipelineCoordinator
    from game_chat_translator.capture.dxcam_capture import DxcamCaptureProvider
    from game_chat_translator.capture.mss_capture import MssCaptureProvider
    from game_chat_translator.capture.router import FallbackCaptureProvider
    from game_chat_translator.capture.service import RegionCaptureService
    from game_chat_translator.classification.classifier import MessageClassifier
    from game_chat_translator.classification.pipeline import ClassificationPipeline
    from game_chat_translator.detection.foreground_window import Win32ForegroundWindowProvider
    from game_chat_translator.language.detector import LocalLanguageDetector
    from game_chat_translator.language.glossary import GlossaryResolver
    from game_chat_translator.profiles.resources import ResourceRegistry
    from game_chat_translator.vision.isolated_service import (
        IsolatedOcrService,
        PaddleOcrProviderFactory,
    )
    from game_chat_translator.vision.line_tracker import LineTracker
    from game_chat_translator.vision.pipeline import OcrPipeline
    from game_chat_translator.vision.preprocess import OpenCvPreprocessor, PreprocessConfig

    paths = ocr_setup.ready_paths()
    if paths is None:
        return None
    detection, recognition = paths
    resources = ResourceRegistry(runtime.resource_root).load_all()
    selected = resources[settings.application.active_profile]
    generation = 1
    ocr = OcrPipeline(
        OpenCvPreprocessor(),
        IsolatedOcrService(PaddleOcrProviderFactory(detection, recognition)),
        LineTracker(),
        initial_generation=generation,
        publish_status=lambda update: _publish_monitoring_status(controller, update.error_code),
    )
    classification = ClassificationPipeline(
        MessageClassifier(selected),
        LocalLanguageDetector(GlossaryResolver(selected.glossary)),
        initial_generation=generation,
    )
    translation = runtime.build_translation_pipeline(initial_generations=(generation,) * 6)
    speaker_observer: Callable[[str, str, float], None] | None = None
    if speakers is not None:

        def observe_speaker(speaker: str, language: str, confidence: float) -> None:
            speakers.observe_message(speaker, language, confidence)

        speaker_observer = observe_speaker
    coordinator = ApplicationPipelineCoordinator(
        ocr,
        classification,
        translation,
        InboundPresentationService(controller),
        target_language=settings.translation.target,
        close_translation=lambda: runtime.release_pipeline(translation),
        observe_speaker=speaker_observer,
    )
    capture = RegionCaptureService(
        FallbackCaptureProvider(DxcamCaptureProvider(), MssCaptureProvider())
    )
    source = LiveFrameSource(
        Win32ForegroundWindowProvider(),
        {profile_id: item.profile for profile_id, item in resources.items()},
        runtime.state_repository(),
        capture,
        active_profile=settings.application.active_profile,
    )
    return MonitoringWorker(
        source,
        coordinator,
        PreprocessConfig.from_profile(selected.profile),
        generation=generation,
        on_failure=lambda code: _publish_monitoring_status(controller, code),
    )


def _activate_reply_services(
    runtime_holder: dict[str, Any],
    monitoring: MonitoringWorker,
    speakers: SpeakerTracker,
    model_path: Path,
    controller: ApplicationController,
    speech_worker: SpeechWorker,
    ui_controller: DesktopUiController,
    settings: AppSettings,
) -> None:
    _close_hold_key(runtime_holder)
    _close_reply(runtime_holder)
    from game_chat_translator.language.glossary import GlossaryResolver
    from game_chat_translator.profiles.resources import ResourceRegistry

    resources = ResourceRegistry(bundled_resource_root()).load_all()
    selected = resources[settings.application.active_profile]
    glossary = GlossaryResolver(selected.glossary)
    pipeline = monitoring.translation_pipeline

    def current_generations() -> ReplyGenerations:
        profile, layout, context, glossary_generation, model, config = pipeline.generations
        return ReplyGenerations(
            profile,
            layout,
            context,
            glossary_generation,
            model,
            config,
            speakers.generation,
        )

    def report(code: str) -> None:
        controller.report_error(
            AppError(
                code=code,
                subsystem="reply",
                severity=ErrorSeverity.RECOVERABLE,
                user_message="The voice reply could not be completed.",
                retryable=True,
            )
        )

    def finish_reply_operation() -> None:
        controller.finish_reply()
        if runtime_holder.pop("pause_after_reply", False):
            controller.pause()
            monitoring.pause()

    reply = ReplyCoordinator(
        hold_key=settings.reply.hold_to_talk,
        minimum_hold_ms=settings.reply.minimum_hold_ms,
        minimum_transcript_confidence=settings.speech_recognition.minimum_confidence,
        recorder_factory=lambda: SoundDeviceAudioRecorder(
            maximum_seconds=settings.speech_recognition.maximum_recording_seconds,
            device=settings.speech_recognition.microphone_device,
        ),
        transcription=IsolatedFasterWhisper(model_path),
        speakers=speakers,
        translation=pipeline,
        generations=current_generations,
        pause_speech=speech_worker.set_paused,
        wait_speech_paused=speech_worker.wait_paused,
        copy_to_clipboard=ui_controller.copy_reply_to_clipboard,
        publish_draft=ui_controller.queue_reply_draft,
        begin_recording=controller.begin_reply_recording,
        begin_processing=controller.begin_reply_processing,
        finish_operation=finish_reply_operation,
        publish_error=report,
        notify_copied=(
            ui_controller.queue_reply_copied
            if settings.reply.show_clipboard_toast
            else lambda: None
        ),
        protected_terms=glossary.protected_terms,
        copy_after_translation=settings.reply.copy_after_translation,
    )

    def key_down(key: str, now: float) -> None:
        reply.key_down(key, now)

    def key_up(key: str, now: float) -> None:
        reply.key_up(key, now)

    observer = WindowsHoldKeyObserver(
        settings.reply.hold_to_talk,
        key_down,
        key_up,
        on_failure=report,
    )
    runtime_holder["reply"] = reply
    runtime_holder["hold_key"] = observer
    observer.start()


def _publish_monitoring_status(controller: ApplicationController, error_code: str | None) -> None:
    if error_code is None:
        return
    controller.report_error(
        AppError(
            code=error_code,
            subsystem="monitoring",
            severity=ErrorSeverity.DEGRADED,
            user_message="Live chat monitoring is temporarily unavailable.",
            retryable=True,
        )
    )


def _speech_settings(settings: AppSettings) -> SpeechSettings:
    sapi_rate = round((settings.speech.rate - 185) / 21.5)
    return SpeechSettings(
        rate=max(-10, min(10, sapi_rate)),
        volume=round(settings.speech.volume * 100),
        voice_id=settings.speech.voice_id,
    )


def _report_safe_error(holder: dict[str, Any], code: str, subsystem: str) -> None:
    controller = holder.get("controller")
    if controller is None:
        return
    controller.report_error(
        AppError(
            code=code,
            subsystem=subsystem,
            severity=ErrorSeverity.DEGRADED,
            user_message=f"{subsystem.capitalize()} is temporarily unavailable.",
            retryable=True,
        )
    )


def _restore_geometry_value(application: Any, window: Any, geometry: WindowGeometry) -> None:
    screens = tuple(application.screens())
    screen_by_id = {str(screen.name()): screen for screen in screens if screen.name()}
    with suppress(OSError, RuntimeError, ValueError):
        screen = screen_by_id.get(geometry.display_id) or application.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(geometry.width, available.width())
        height = min(geometry.height, available.height())
        x = min(max(geometry.x, available.left()), available.right() - width + 1)
        y = min(max(geometry.y, available.top()), available.bottom() - height + 1)
        window.restore_geometry((x, y, width, height))


def _close_storage(
    worker: _StorageWorker,
    runtime_holder: dict[str, Any],
) -> None:
    worker.close()
    runtime = runtime_holder.get("runtime")
    if isinstance(runtime, CoreRuntime):
        runtime.close_storage()


def _close_compute(
    tasks: _BackgroundTasks,
    runtime_holder: dict[str, Any],
) -> None:
    tasks.close()
    monitoring = runtime_holder.get("monitoring")
    if isinstance(monitoring, MonitoringWorker):
        monitoring.close()
    runtime = runtime_holder.get("runtime")
    if isinstance(runtime, CoreRuntime):
        runtime.close_compute()


def _close_reply(runtime_holder: dict[str, Any]) -> None:
    reply, runtime_holder["reply"] = runtime_holder.get("reply"), None
    if isinstance(reply, ReplyCoordinator):
        reply.close()


def _close_hotkeys(runtime_holder: dict[str, Any]) -> None:
    _close_hold_key(runtime_holder)
    observer, runtime_holder["shortcuts"] = runtime_holder.get("shortcuts"), None
    if isinstance(observer, WindowsShortcutObserver):
        observer.close()


def _close_hold_key(runtime_holder: dict[str, Any]) -> None:
    observer, runtime_holder["hold_key"] = runtime_holder.get("hold_key"), None
    if isinstance(observer, WindowsHoldKeyObserver):
        observer.close()


def _pause_monitoring(runtime_holder: dict[str, Any]) -> None:
    monitoring = runtime_holder.get("monitoring")
    if isinstance(monitoring, MonitoringWorker):
        monitoring.pause()


def _capture_foreground_client() -> tuple[WindowIdentity, RawFrame]:
    from game_chat_translator.capture.base import CaptureError
    from game_chat_translator.detection.foreground_window import Win32ForegroundWindowProvider

    window = Win32ForegroundWindowProvider().get_active_window()
    if window is None or window.minimized:
        raise CaptureError("foreground game client is unavailable")
    return window, _capture_client_bounds(window)


def _capture_client_bounds(window: WindowIdentity) -> RawFrame:
    from game_chat_translator.capture.base import CaptureError
    from game_chat_translator.capture.mss_capture import MssCaptureProvider
    from game_chat_translator.detection.layout_resolver import ScreenRegion

    bounds = window.client_bounds
    provider = MssCaptureProvider()
    try:
        provider.start(ScreenRegion(bounds.left, bounds.top, bounds.width, bounds.height))
        frame = provider.next_frame()
    finally:
        provider.close()
    if frame is None or frame.width != bounds.width or frame.height != bounds.height:
        raise CaptureError("foreground client capture did not match its bounds")
    return frame


def _complete_retry_capture(
    window: WindowIdentity, completed: Callable[[bytes | None], None]
) -> None:
    try:
        completed(_capture_client_bounds(window).pixels)
    except Exception:
        completed(None)


def _calibration_restore_target(previous: LifecycleState, *, saved: bool) -> LifecycleState:
    if saved and previous is LifecycleState.NEEDS_SETUP:
        return LifecycleState.MONITORING
    return previous


class _CalibrationHandoffError(RuntimeError):
    pass


def _persist_calibration_after_generation_handoff(
    runtime: CoreRuntime,
    monitoring: MonitoringWorker | None,
    repository: Any,
    profile_id: str,
    monitor_id: str,
    region: ChatRegion,
) -> None:
    try:
        layout_generation = runtime.advance_layout_generation()
        if monitoring is not None:
            monitoring.advance_layout_generation(layout_generation)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise _CalibrationHandoffError("calibration generation handoff failed") from exc
    repository.save_calibration(profile_id, monitor_id, region, None)
