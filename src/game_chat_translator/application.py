from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from uuid import UUID

from game_chat_translator.events import AppError, ErrorSeverity
from game_chat_translator.lifecycle import Lifecycle, LifecycleState
from game_chat_translator.models import ClassifiedMessage, MessageClass, TranslationResult
from game_chat_translator.settings import AppSettings
from game_chat_translator.ui.event_queue import PresentedMessage, UiEventQueue, UiQueueClosed


class DashboardCloseAction(StrEnum):
    HIDE = "hide"
    QUIT = "quit"


@dataclass(frozen=True, slots=True)
class ShutdownServices:
    stop_capture: Callable[[], None] = lambda: None
    close_compute: Callable[[], None] = lambda: None
    close_speech: Callable[[], None] = lambda: None
    close_audio: Callable[[], None] = lambda: None
    close_hotkeys: Callable[[], None] = lambda: None
    close_ui: Callable[[], None] = lambda: None
    close_storage: Callable[[], None] = lambda: None


@dataclass(frozen=True, slots=True)
class HistoryServices:
    persist: Callable[[PresentedMessage, int], None] = lambda _message, _days: None
    clear_context: Callable[[], None] = lambda: None
    clear_translation_cache: Callable[[], None] = lambda: None
    clear_pending_writes: Callable[[], None] = lambda: None
    clear_persisted: Callable[[], None] = lambda: None


@dataclass(frozen=True, slots=True)
class PresentationOutcome:
    message: PresentedMessage
    visualized: bool
    speech_admitted: bool


class ApplicationController:
    """Thread-safe application lifecycle and presentation owner, independent of Qt/providers."""

    def __init__(
        self,
        settings: AppSettings,
        ui_events: UiEventQueue,
        *,
        shutdown: ShutdownServices | None = None,
        history: HistoryServices | None = None,
        queue_speech: Callable[[PresentedMessage], bool | None] = lambda _message: True,
        set_speech_muted: Callable[[bool], None] = lambda _muted: None,
        memory_history_limit: int = 500,
        dedupe_limit: int = 4096,
        speech_backlog_limit: int = 64,
    ) -> None:
        if memory_history_limit <= 0 or dedupe_limit <= 0 or speech_backlog_limit <= 0:
            raise ValueError("history and dedupe limits must be positive")
        self._settings = settings
        self._ui_events = ui_events
        self._shutdown = shutdown or ShutdownServices()
        self._history_services = history or HistoryServices()
        self._queue_speech = queue_speech
        self._set_speech_muted = set_speech_muted
        self._memory_history: deque[PresentedMessage] = deque(maxlen=memory_history_limit)
        self._seen_order: deque[UUID] = deque()
        self._seen: set[UUID] = set()
        self._dedupe_limit = dedupe_limit
        self._pending_speech: deque[PresentedMessage] = deque()
        self._speech_backlog_limit = speech_backlog_limit
        self._lifecycle = Lifecycle()
        self._lock = Lock()
        self._quit_started = False
        self._muted = not settings.speech.enabled
        self._shutdown_errors: tuple[AppError, ...] = ()

    @property
    def state(self) -> LifecycleState:
        with self._lock:
            return self._lifecycle.state

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def history(self) -> tuple[PresentedMessage, ...]:
        with self._lock:
            return tuple(self._memory_history)

    @property
    def shutdown_errors(self) -> tuple[AppError, ...]:
        with self._lock:
            return self._shutdown_errors

    def update_settings(self, settings: AppSettings) -> None:
        with self._lock:
            if self._quit_started:
                return
            self._settings = settings

    def start(self, *, needs_setup: bool = False, degraded: bool = False) -> None:
        target = (
            LifecycleState.DEGRADED
            if degraded
            else LifecycleState.NEEDS_SETUP
            if needs_setup
            else LifecycleState.PAUSED
        )
        with self._lock:
            if self._lifecycle.state is not LifecycleState.STARTING:
                return
            self._lifecycle.transition(target)
        self._safe_status("lifecycle", target.value)

    def pause(self) -> None:
        with self._lock:
            if self._quit_started or self._lifecycle.state is LifecycleState.PAUSED:
                return
            if self._lifecycle.state not in {
                LifecycleState.MONITORING,
                LifecycleState.DEGRADED,
                LifecycleState.NEEDS_SETUP,
            }:
                return
            self._lifecycle.transition(LifecycleState.PAUSED)
        self._safe_status("lifecycle", LifecycleState.PAUSED.value)

    def resume(self) -> None:
        with self._lock:
            if self._quit_started or self._lifecycle.state is LifecycleState.MONITORING:
                return
            if self._lifecycle.state not in {
                LifecycleState.PAUSED,
                LifecycleState.NEEDS_SETUP,
                LifecycleState.DEGRADED,
            }:
                return
            self._lifecycle.transition(LifecycleState.MONITORING)
        self._safe_status("lifecycle", LifecycleState.MONITORING.value)

    def restore_operational_state(self, state: LifecycleState) -> None:
        if state not in {
            LifecycleState.PAUSED,
            LifecycleState.MONITORING,
            LifecycleState.NEEDS_SETUP,
            LifecycleState.DEGRADED,
        }:
            raise ValueError("state is not restorable after an application operation")
        with self._lock:
            if self._quit_started or self._lifecycle.state is state:
                return
            self._lifecycle.transition(state)
        self._safe_status("lifecycle", state.value)

    def close_dashboard(self, *, tray_available: bool = True) -> DashboardCloseAction:
        if self._settings.application.close_to_tray and tray_available:
            return DashboardCloseAction.HIDE
        return DashboardCloseAction.QUIT

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            if self._quit_started or self._muted is muted:
                return
            self._muted = muted
            if muted:
                self._pending_speech.clear()
        self._set_speech_muted(muted)
        self._safe_status("speech", "muted" if muted else "enabled")

    def present(self, message: PresentedMessage) -> bool:
        return self.present_with_outcome(message).visualized

    def present_with_outcome(self, message: PresentedMessage) -> PresentationOutcome:
        with self._lock:
            if self._quit_started or message.message_id in self._seen:
                return PresentationOutcome(message, False, False)
            self._seen.add(message.message_id)
            self._seen_order.append(message.message_id)
            while len(self._seen_order) > self._dedupe_limit:
                self._seen.discard(self._seen_order.popleft())
            self._memory_history.append(message)
            persist = self._settings.privacy.persist_message_history
            retention_days = self._settings.privacy.history_retention_days
        try:
            self._ui_events.publish_message(message, cancelled=lambda: self._quit_started)
        except UiQueueClosed:
            return PresentationOutcome(message, False, False)
        if persist:
            try:
                self._history_services.persist(message, retention_days)
            except Exception:
                self.report_error(
                    AppError(
                        code="HISTORY_WRITE_FAILED",
                        subsystem="storage",
                        severity=ErrorSeverity.RECOVERABLE,
                        user_message="Message history could not be saved.",
                        retryable=True,
                    )
                )
        needs_speech = (
            message.classification is MessageClass.PLAYER_INBOUND
            and message.announce
            and not self.muted
        )
        speech_admitted = not needs_speech or self.admit_speech(message)
        return PresentationOutcome(message, True, speech_admitted)

    def admit_speech(self, message: PresentedMessage) -> bool:
        with self._lock:
            if self._quit_started or self._muted:
                return True
            if len(self._pending_speech) >= self._speech_backlog_limit:
                return False
        try:
            if self._queue_speech(message) is not False:
                return True
        except Exception:
            self.report_error(
                AppError(
                    code="SPEECH_QUEUE_FAILED",
                    subsystem="speech",
                    severity=ErrorSeverity.DEGRADED,
                    user_message="Speech is temporarily unavailable.",
                    retryable=True,
                )
            )
            return True
        with self._lock:
            if self._quit_started or self._muted:
                return True
            if len(self._pending_speech) >= self._speech_backlog_limit:
                return False
            self._pending_speech.append(message)
            return True

    def flush_speech(self) -> bool:
        while True:
            with self._lock:
                if self._quit_started or self._muted or not self._pending_speech:
                    return True
                message = self._pending_speech[0]
            try:
                if self._queue_speech(message) is False:
                    return False
            except Exception:
                self.report_error(
                    AppError(
                        code="SPEECH_QUEUE_FAILED",
                        subsystem="speech",
                        severity=ErrorSeverity.DEGRADED,
                        user_message="Speech is temporarily unavailable.",
                        retryable=True,
                    )
                )
                return False
            with self._lock:
                if (
                    self._pending_speech
                    and self._pending_speech[0].message_id == message.message_id
                ):
                    self._pending_speech.popleft()

    def report_error(self, error: AppError) -> None:
        with self._lock:
            if self._quit_started:
                return
        try:
            self._ui_events.publish_error(error, cancelled=lambda: self._quit_started)
        except UiQueueClosed:
            return

    def clear_history(self) -> None:
        self.clear_visible_history()
        self.clear_history_backing()

    def clear_visible_history(self) -> None:
        with self._lock:
            self._memory_history.clear()
            self._seen.clear()
            self._seen_order.clear()
            self._pending_speech.clear()
        self._ui_events.clear_messages()

    def clear_history_backing(self) -> None:
        for clear in (
            self._history_services.clear_context,
            self._history_services.clear_translation_cache,
            self._history_services.clear_pending_writes,
            self._history_services.clear_persisted,
        ):
            try:
                clear()
            except Exception:
                self.report_error(
                    AppError(
                        code="HISTORY_CLEAR_FAILED",
                        subsystem="storage",
                        severity=ErrorSeverity.RECOVERABLE,
                        user_message="Some history data could not be cleared.",
                        retryable=True,
                    )
                )

    def quit(self) -> bool:
        with self._lock:
            if self._quit_started:
                return False
            self._quit_started = True
            if self._lifecycle.state is not LifecycleState.STOPPING:
                self._lifecycle.transition(LifecycleState.STOPPING)

        failures: list[AppError] = []
        ordered = (
            ("capture", self._shutdown.stop_capture),
            ("compute", self._shutdown.close_compute),
            ("speech", self._shutdown.close_speech),
            ("audio", self._shutdown.close_audio),
            ("hotkeys", self._shutdown.close_hotkeys),
            ("ui", self._shutdown.close_ui),
            ("storage", self._shutdown.close_storage),
        )
        for subsystem, close in ordered:
            try:
                close()
            except Exception:
                failures.append(
                    AppError(
                        code="SHUTDOWN_STEP_FAILED",
                        subsystem=subsystem,
                        severity=ErrorSeverity.RECOVERABLE,
                        user_message="One application component did not stop cleanly.",
                    )
                )
        self._ui_events.close()
        with self._lock:
            self._shutdown_errors = tuple(failures)
        return True

    def _safe_status(self, key: str, value: str) -> None:
        try:
            self._ui_events.publish_status(key, value)
        except UiQueueClosed:
            return


class InboundPresentationService:
    """Convert classifier/translator output into the single UI/TTS publication path."""

    def __init__(self, controller: ApplicationController) -> None:
        self._controller = controller

    def publish(
        self,
        message: ClassifiedMessage,
        translation: TranslationResult | None,
        *,
        created_at: datetime | None = None,
        announce: bool | None = None,
    ) -> bool:
        return self.publish_outcome(
            message,
            translation,
            created_at=created_at,
            announce=announce,
        ).visualized

    def publish_outcome(
        self,
        message: ClassifiedMessage,
        translation: TranslationResult | None,
        *,
        created_at: datetime | None = None,
        announce: bool | None = None,
    ) -> PresentationOutcome:
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("presentation timestamp must be timezone-aware")
        natural = translation.natural_text if translation is not None else message.body
        warning_codes = translation.warnings if translation is not None else ()
        presented = PresentedMessage(
            message.message_id,
            timestamp.astimezone(UTC),
            message.classification,
            message.speaker,
            message.body,
            natural,
            warning_codes,
            (
                message.classification is MessageClass.PLAYER_INBOUND
                if announce is None
                else announce
            ),
        )
        return self._controller.present_with_outcome(presented)

    def flush_speech(self) -> bool:
        return self._controller.flush_speech()

    def admit_speech(self, message: PresentedMessage) -> bool:
        return self._controller.admit_speech(message)
