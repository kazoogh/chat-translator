from __future__ import annotations

from typing import Protocol

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.ui.translation_window import TranslationRow


class DashboardController(Protocol):
    def retry_runtime(self) -> None: ...

    def toggle_pause(self) -> None: ...

    def calibrate(self) -> None: ...

    def clear_history(self) -> None: ...

    def open_model_manager(self) -> None: ...

    def open_learned_terms(self) -> None: ...

    def export_diagnostics(self) -> None: ...

    def dashboard_hidden(self) -> None: ...

    def quit_application(self) -> None: ...

    def set_speech_rate(self, rate: int) -> None: ...

    def set_speech_volume(self, volume_percent: int) -> None: ...

    def select_speech_voice(self, voice_id: str | None) -> None: ...

    def open_licenses(self) -> None: ...

    def download_model(self, model_id: str) -> None: ...

    def remove_model(self, model_id: str) -> None: ...

    def set_learned_term_status(self, alias: str, status: str) -> None: ...

    def cancel_reply(self) -> None: ...

    def retry_reply(self, text: str) -> None: ...

    def select_reply_target(self, speaker_id: str) -> None: ...


def create_dashboard(
    controller: DashboardController,
    *,
    close_to_tray: bool = True,
    speech_rate: int = 185,
    speech_volume_percent: int = 90,
    voices: tuple[tuple[str, str], ...] = (),
    selected_voice_id: str | None = None,
    hotkeys: tuple[tuple[str, str], ...] = (),
    models: tuple[tuple[str, str], ...] = (),
    learned_terms: tuple[tuple[str, str, str], ...] = (),
    active_profile: str = "stalzone.default",
    maximum_translation_rows: int = 100,
) -> object:
    """Create the thin dashboard view without importing Qt at module import time."""
    if maximum_translation_rows <= 0:
        raise ValueError("maximum translation rows must be positive")
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QCloseEvent, QImage, QPixmap, QResizeEvent
        from PySide6.QtWidgets import (
            QComboBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QMainWindow,
            QPushButton,
            QScrollArea,
            QSlider,
            QStackedWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError("Install the pinned UI extra to open the dashboard") from exc

    class Dashboard(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("dashboard")
            self.setWindowTitle("Game Chat Translator")
            self.setMinimumSize(900, 620)
            self.resize(1180, 760)
            self._close_to_tray = close_to_tray
            self._active_profile = active_profile
            self._status_label: QLabel | None = None
            self._setup_label: QLabel | None = None
            self._pause_button: QPushButton | None = None
            self._calibrate_button: QPushButton | None = None
            self._calibration_status: QLabel | None = None
            self._capture_preview: QLabel | None = None
            self._capture_preview_meta: QLabel | None = None
            self._capture_preview_pixmap: QPixmap | None = None
            self._model_status: QLabel | None = None
            self._model_labels: dict[str, QLabel] = {}
            self._model_buttons: dict[str, tuple[QPushButton, QPushButton]] = {}
            self._voice_combo: QComboBox | None = None
            self._model_list: QVBoxLayout | None = None
            self._learned_list: QVBoxLayout | None = None
            self._reply_status: QLabel | None = None
            self._reply_transcript: QLabel | None = None
            self._reply_translation: QLabel | None = None
            self._reply_edit: QLineEdit | None = None
            self._reply_targets: QComboBox | None = None
            self._translation_rows: QVBoxLayout | None = None
            self._translation_scroll: QScrollArea | None = None
            self._translation_empty: QLabel | None = None
            self._translation_ids: set[str] = set()
            shell = QWidget(self)
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            shell_layout.setSpacing(0)
            navigation_panel = QWidget()
            navigation_panel.setObjectName("navigation-panel")
            navigation_layout = QVBoxLayout(navigation_panel)
            navigation_layout.setContentsMargins(14, 20, 14, 14)
            navigation_layout.setSpacing(14)
            brand = QLabel("GAME CHAT\nTRANSLATOR")
            brand.setObjectName("app-brand")
            navigation_layout.addWidget(brand)
            navigation = QListWidget()
            navigation.setObjectName("dashboard-navigation")
            navigation.setFixedWidth(210)
            pages = QStackedWidget()
            pages.setObjectName("dashboard-pages")
            for name in (
                "Status",
                "Capture",
                "Profiles",
                "Translation Models",
                "Audio & Voice",
                "Hotkeys",
                "History",
                "Diagnostics",
            ):
                navigation.addItem(name)
                pages.addWidget(self._page(name))
            navigation.currentRowChanged.connect(pages.setCurrentIndex)
            navigation.setCurrentRow(0)
            navigation_layout.addWidget(navigation, 1)
            footer = QLabel("Local • Private • Offline")
            footer.setObjectName("navigation-footer")
            navigation_layout.addWidget(footer)
            shell_layout.addWidget(navigation_panel)
            shell_layout.addWidget(pages, 1)
            self.setCentralWidget(shell)
            self._apply_theme()

        def _apply_theme(self) -> None:
            self.setStyleSheet(
                """
                QMainWindow, QWidget { background: #0e1415; color: #dee4e4; }
                QWidget#navigation-panel { background: #171d1d; }
                QLabel#app-brand {
                    color: #55d8e1; font-size: 16px; font-weight: 700;
                    padding: 4px 8px 14px 8px;
                }
                QListWidget#dashboard-navigation {
                    background: transparent; border: 0; outline: 0; color: #bbc9ca;
                    font-size: 14px;
                }
                QListWidget#dashboard-navigation::item {
                    min-height: 42px; padding: 0 12px; border-radius: 7px;
                }
                QListWidget#dashboard-navigation::item:hover {
                    background: #1b2829; color: #dee4e4;
                }
                QListWidget#dashboard-navigation::item:selected {
                    background: #183033; color: #55d8e1;
                    border-left: 3px solid #55d8e1;
                }
                QLabel#navigation-footer { color: #758687; padding: 8px; }
                QLabel#page-heading { color: #dee4e4; font-size: 22px; font-weight: 600; }
                QLabel#status-summary { color: #55d8e1; font-size: 16px; font-weight: 600; }
                QLabel#setup-summary, QLabel#translation-empty, QLabel#models-loading,
                QLabel#learned-terms-empty { color: #bbc9ca; }
                QLabel#capture-preview {
                    background: #090f10; border: 1px solid #3c494a;
                    border-radius: 10px; color: #758687; padding: 10px;
                }
                QLabel#capture-preview-meta { color: #758687; }
                QLabel#translations-heading { font-size: 18px; font-weight: 600; }
                QLabel[translation="true"] {
                    background: #171d1d; border-left: 2px solid #55d8e1;
                    padding: 12px; margin: 4px; font-size: 14px;
                }
                QScrollArea#translation-feed {
                    border: 1px solid #3c494a; border-radius: 10px; background: #090f10;
                }
                QWidget#model-card {
                    background: #1b2121; border: 1px solid #3c494a; border-radius: 10px;
                }
                QLabel#model-description { font-size: 14px; }
                QPushButton {
                    background: #252b2b; border: 1px solid #3c494a; border-radius: 7px;
                    padding: 8px 14px; color: #dee4e4;
                }
                QPushButton:hover { border-color: #55d8e1; color: #55d8e1; }
                QPushButton:pressed { background: #303636; }
                QPushButton#action-pause--resume, QPushButton#action-calibrate-chat-area {
                    background: #00adb5; color: #002022; border-color: #55d8e1;
                    font-weight: 600;
                }
                QComboBox, QLineEdit {
                    background: #1b2121; border: 1px solid #3c494a; border-radius: 6px;
                    padding: 7px; color: #dee4e4;
                }
                QSlider::groove:horizontal { height: 4px; background: #3c494a; }
                QSlider::handle:horizontal {
                    width: 14px; margin: -5px 0; border-radius: 7px; background: #55d8e1;
                }
                """
            )

        def _page(self, name: str) -> QWidget:
            page = QWidget()
            page.setObjectName(f"page-{name.casefold().replace(' ', '-').replace('&', 'and')}")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(12)
            heading = QLabel(name)
            heading.setObjectName("page-heading")
            heading.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(heading)
            if name == "Status":
                self._status_label = QLabel("Starting local services…")
                self._status_label.setObjectName("status-summary")
                self._status_label.setWordWrap(True)
                layout.addWidget(self._status_label)
                self._setup_label = QLabel()
                self._setup_label.setObjectName("setup-summary")
                self._setup_label.setWordWrap(True)
                layout.addWidget(self._setup_label)
                self.set_setup_state(ocr_ready=False, calibrated=False, monitoring=False)
            actions = {
                "Status": (
                    ("Pause / Resume", controller.toggle_pause),
                    ("Retry Setup", controller.retry_runtime),
                ),
                "Capture": (("Calibrate Chat Area", controller.calibrate),),
                "History": (("Clear History", controller.clear_history),),
                "Diagnostics": (
                    ("Export Diagnostics", controller.export_diagnostics),
                    ("Licenses", controller.open_licenses),
                ),
            }.get(name, ())
            for label, callback in actions:
                button = QPushButton(label)
                object_name = label.casefold().replace(" ", "-").replace("/", "")
                button.setObjectName("action-" + object_name)
                button.clicked.connect(callback)
                layout.addWidget(button)
                if label == "Pause / Resume":
                    self._pause_button = button
                    button.setEnabled(False)
                    button.setText("Finish setup to start monitoring")
                elif label == "Calibrate Chat Area":
                    self._calibrate_button = button
                    button.setEnabled(False)
                    button.setText("Starting calibration services…")
            if name == "Status":
                translations_heading = QLabel("Live Translations")
                translations_heading.setObjectName("translations-heading")
                layout.addWidget(translations_heading)
                explanation = QLabel(
                    "Incoming player messages appear here after the OCR model is installed "
                    "and the chat area is calibrated. Hover over a translation to see the "
                    "recognized source text."
                )
                explanation.setWordWrap(True)
                layout.addWidget(explanation)
                scroll = QScrollArea()
                scroll.setObjectName("translation-feed")
                scroll.setWidgetResizable(True)
                content = QWidget()
                rows = QVBoxLayout(content)
                empty = QLabel("No translations yet")
                empty.setObjectName("translation-empty")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                rows.addWidget(empty)
                rows.addStretch(1)
                scroll.setWidget(content)
                self._translation_scroll = scroll
                self._translation_rows = rows
                self._translation_empty = empty
                layout.addWidget(scroll, 1)
            if name == "Translation Models":
                instructions = QLabel(
                    "No API key is required. Everything runs locally after setup. Download / "
                    "Verify the required OCR bundle first. Voice recognition and larger "
                    "translation models are optional."
                )
                instructions.setWordWrap(True)
                layout.addWidget(instructions)
                self._model_status = QLabel("Checking installed models…")
                self._model_status.setObjectName("model-status")
                self._model_status.setWordWrap(True)
                layout.addWidget(self._model_status)
                self._model_list = QVBoxLayout()
                layout.addLayout(self._model_list)
                self.set_models(models)
            if name == "Profiles":
                profile = QLabel(f"Active game profile: {active_profile}")
                profile.setObjectName("active-profile")
                layout.addWidget(profile)
                note = QLabel(
                    "The active profile controls game detection, chat parsing, and glossary "
                    "rules. Learned terms appear below after monitoring begins."
                )
                note.setWordWrap(True)
                layout.addWidget(note)
                self._learned_list = QVBoxLayout()
                layout.addLayout(self._learned_list)
                self.set_learned_terms(learned_terms)
            if name == "Capture":
                instructions = QLabel(
                    "Open the game, start calibration, switch back to the game, then draw a "
                    "box around chat on the frozen screenshot and save it."
                )
                instructions.setWordWrap(True)
                layout.addWidget(instructions)
                self._calibration_status = QLabel("Waiting for local storage and capture services…")
                self._calibration_status.setObjectName("calibration-status")
                self._calibration_status.setWordWrap(True)
                layout.addWidget(self._calibration_status)
                self._capture_preview = QLabel(
                    "The selected chat-area snapshot will appear here after calibration."
                )
                self._capture_preview.setObjectName("capture-preview")
                self._capture_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._capture_preview.setMinimumHeight(260)
                self._capture_preview.setMaximumHeight(430)
                self._capture_preview.setWordWrap(True)
                layout.addWidget(self._capture_preview, 1)
                self._capture_preview_meta = QLabel(
                    "Preview is kept in memory only and is never saved to disk."
                )
                self._capture_preview_meta.setObjectName("capture-preview-meta")
                layout.addWidget(self._capture_preview_meta)
            if name == "Audio & Voice":
                self._reply_status = QLabel("Reply: idle")
                self._reply_status.setObjectName("reply-status")
                self._reply_transcript = QLabel("")
                self._reply_transcript.setObjectName("reply-transcript")
                self._reply_transcript.setWordWrap(True)
                self._reply_translation = QLabel("")
                self._reply_translation.setObjectName("reply-translation")
                self._reply_translation.setWordWrap(True)
                self._reply_edit = QLineEdit()
                self._reply_edit.setObjectName("reply-edit")
                self._reply_edit.setPlaceholderText("Edit translated reply before copying")
                self._reply_targets = QComboBox()
                self._reply_targets.setObjectName("reply-target")
                retry = QPushButton("Copy Edited Reply")
                retry.setObjectName("reply-retry")
                retry.clicked.connect(
                    lambda: controller.retry_reply(
                        self._reply_edit.text() if self._reply_edit is not None else ""
                    )
                )
                choose = QPushButton("Use Selected Target")
                choose.setObjectName("reply-choose-target")
                choose.clicked.connect(
                    lambda: controller.select_reply_target(
                        str(self._reply_targets.currentData() or "")
                        if self._reply_targets is not None
                        else ""
                    )
                )
                cancel = QPushButton("Cancel Reply")
                cancel.setObjectName("reply-cancel")
                cancel.clicked.connect(controller.cancel_reply)
                layout.addWidget(self._reply_status)
                layout.addWidget(self._reply_transcript)
                layout.addWidget(self._reply_translation)
                layout.addWidget(self._reply_edit)
                layout.addWidget(self._reply_targets)
                layout.addWidget(choose)
                layout.addWidget(retry)
                layout.addWidget(cancel)
                rate_label = QLabel("Speech rate")
                rate = QSlider(Qt.Orientation.Horizontal)
                rate.setObjectName("speech-rate")
                rate.setRange(50, 400)
                rate.setValue(speech_rate)
                rate.valueChanged.connect(controller.set_speech_rate)
                layout.addWidget(rate_label)
                layout.addWidget(rate)
                volume_label = QLabel("Speech volume")
                volume = QSlider(Qt.Orientation.Horizontal)
                volume.setObjectName("speech-volume")
                volume.setRange(0, 100)
                volume.setValue(speech_volume_percent)
                volume.valueChanged.connect(controller.set_speech_volume)
                layout.addWidget(volume_label)
                layout.addWidget(volume)
                voice = QComboBox()
                self._voice_combo = voice
                voice.setObjectName("speech-voice")
                voice.addItem("System default", None)
                for voice_id, description in voices:
                    voice.addItem(description, voice_id)
                if selected_voice_id is not None:
                    index = voice.findData(selected_voice_id)
                    if index >= 0:
                        voice.setCurrentIndex(index)
                voice.currentIndexChanged.connect(
                    lambda _index: controller.select_speech_voice(voice.currentData())
                )
                layout.addWidget(voice)
            if name == "Hotkeys":
                for action, shortcut in hotkeys:
                    layout.addWidget(QLabel(f"{action}: {shortcut}"))
            layout.addStretch(1)
            return page

        def set_reply_draft(self, draft: object) -> None:
            status = getattr(draft, "status", "idle")
            rendered_status = getattr(status, "value", str(status))
            transcript = str(getattr(draft, "transcript", "") or "")
            target = str(getattr(draft, "target_speaker", "") or "")
            translation = str(getattr(draft, "translated_text", "") or "")
            if self._reply_status is not None:
                self._reply_status.setText(f"Reply: {rendered_status}")
            if self._reply_transcript is not None:
                self._reply_transcript.setText(f"You said: {transcript}" if transcript else "")
            if self._reply_translation is not None:
                prefix = f"To {target}: " if target else ""
                self._reply_translation.setText(prefix + translation if translation else "")
            if self._reply_edit is not None and translation:
                self._reply_edit.setText(translation)

        def set_reply_targets(self, targets: tuple[tuple[str, str], ...]) -> None:
            if self._reply_targets is None:
                return
            self._reply_targets.clear()
            self._reply_targets.addItem("Choose a recent speaker", None)
            for speaker_id, display_name in targets:
                self._reply_targets.addItem(display_name, speaker_id)

        def set_status(self, status: str) -> None:
            if self._status_label is not None:
                self._status_label.setText(status)

        def set_setup_state(self, *, ocr_ready: bool, calibrated: bool, monitoring: bool) -> None:
            if self._setup_label is None:
                return
            ocr = "Ready" if ocr_ready else "Download required"
            capture = "Ready" if calibrated else "Calibration required"
            state = "Running" if monitoring else "Waiting for setup"
            self._setup_label.setText(
                f"Profile: {self._active_profile}\n"
                f"OCR models: {ocr}\n"
                f"Chat area: {capture}\n"
                f"Monitoring: {state}"
            )
            if self._pause_button is not None:
                can_monitor = ocr_ready and calibrated
                self._pause_button.setEnabled(can_monitor)
                self._pause_button.setText(
                    "Pause Monitoring"
                    if monitoring
                    else "Resume Monitoring"
                    if can_monitor
                    else "Finish setup to start monitoring"
                )

        def set_calibration_available(self, available: bool) -> None:
            if self._calibrate_button is not None:
                self._calibrate_button.setEnabled(available)
                self._calibrate_button.setText(
                    "Calibrate Chat Area" if available else "Calibration unavailable"
                )

        def set_calibration_status(self, status: str) -> None:
            if self._calibration_status is not None:
                self._calibration_status.setText(status)

        def set_capture_preview(self, frame: RawFrame) -> None:
            if self._capture_preview is None:
                return
            if (
                frame.pixel_format != "BGRA"
                or frame.width <= 0
                or frame.height <= 0
                or len(frame.pixels) != frame.width * frame.height * 4
            ):
                return
            image = QImage(
                frame.pixels,
                frame.width,
                frame.height,
                frame.width * 4,
                QImage.Format.Format_ARGB32,
            ).copy()
            self._capture_preview_pixmap = QPixmap.fromImage(image)
            self._render_capture_preview()
            if self._capture_preview_meta is not None:
                self._capture_preview_meta.setText(
                    f"Selected area: {frame.width} x {frame.height} pixels • memory-only preview"
                )

        def _render_capture_preview(self) -> None:
            label = self._capture_preview
            pixmap = self._capture_preview_pixmap
            if label is None or pixmap is None:
                return
            target = label.size()
            target.setWidth(max(1, target.width() - 20))
            target.setHeight(max(1, target.height() - 20))
            label.setPixmap(
                pixmap.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        def resizeEvent(self, event: QResizeEvent) -> None:
            super().resizeEvent(event)
            self._render_capture_preview()

        def set_model_status(self, status: str) -> None:
            if self._model_status is not None:
                self._model_status.setText(status)

        def set_model_busy(self, model_id: str, busy: bool) -> None:
            buttons = self._model_buttons.get(model_id)
            if buttons is None:
                return
            for button in buttons:
                button.setEnabled(not busy)

        def set_model_ready(self, model_id: str, ready: bool) -> None:
            label = self._model_labels.get(model_id)
            if label is not None:
                description = str(label.property("base_description") or label.text())
                label.setText(f"{description} — {'Ready' if ready else 'Not installed'}")
            buttons = self._model_buttons.get(model_id)
            if buttons is not None:
                download, remove = buttons
                download.setEnabled(not ready)
                remove.setEnabled(ready)

        def append_translation(self, row: TranslationRow) -> None:
            rows = self._translation_rows
            if rows is None or row.message_id in self._translation_ids:
                return
            if self._translation_empty is not None:
                self._translation_empty.hide()
            label = QLabel(f"{row.speaker}: {row.natural_text}")
            label.setObjectName(f"translation-{row.message_id}")
            label.setProperty("message_id", row.message_id)
            label.setProperty("translation", True)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setToolTip(row.source_text)
            rows.insertWidget(rows.count() - 1, label)
            self._translation_ids.add(row.message_id)
            while self.message_count > maximum_translation_rows:
                for index in range(rows.count() - 1):
                    widget = rows.itemAt(index).widget()
                    if widget is None or not widget.property("message_id"):
                        continue
                    item = rows.takeAt(index)
                    removed = item.widget()
                    if removed is not None:
                        self._translation_ids.discard(str(removed.property("message_id")))
                        removed.setParent(None)
                        removed.deleteLater()
                    break
            if self._translation_scroll is not None:
                scroll = self._translation_scroll

                def scroll_to_latest() -> None:
                    bar = scroll.verticalScrollBar()
                    bar.setValue(bar.maximum())

                QTimer.singleShot(0, scroll_to_latest)

        def clear_messages(self) -> None:
            rows = self._translation_rows
            if rows is None:
                return
            for index in range(rows.count() - 2, -1, -1):
                widget = rows.itemAt(index).widget()
                if widget is None or not widget.property("message_id"):
                    continue
                item = rows.takeAt(index)
                removed = item.widget()
                if removed is not None:
                    removed.setParent(None)
                    removed.deleteLater()
            self._translation_ids.clear()
            if self._translation_empty is not None:
                self._translation_empty.show()

        @property
        def message_count(self) -> int:
            rows = self._translation_rows
            if rows is None:
                return 0
            return len(self._translation_ids)

        def set_voices(self, available: tuple[tuple[str, str], ...], selected: str | None) -> None:
            if self._voice_combo is None:
                return
            voice = self._voice_combo
            voice.blockSignals(True)
            voice.clear()
            voice.addItem("System default", None)
            for voice_id, description in available:
                voice.addItem(description, voice_id)
            index = voice.findData(selected)
            voice.setCurrentIndex(index if index >= 0 else 0)
            voice.blockSignals(False)

        def set_models(self, available: tuple[tuple[str, str], ...]) -> None:
            layout = self._model_list
            if layout is None:
                return
            self._clear_layout(layout)
            self._model_labels.clear()
            self._model_buttons.clear()
            if not available:
                placeholder = QLabel("Loading local model status…")
                placeholder.setObjectName("models-loading")
                layout.addWidget(placeholder)
                return
            for model_id, description in available:
                card = QWidget()
                card.setObjectName("model-card")
                card_layout = QVBoxLayout(card)
                model_label = QLabel(description)
                model_label.setObjectName("model-description")
                model_label.setWordWrap(True)
                ready = description.rstrip().endswith("Ready")
                base_description = description.rsplit(" — ", 1)[0]
                model_label.setProperty("base_description", base_description)
                self._model_labels[model_id] = model_label
                card_layout.addWidget(model_label)
                if model_id == "builtin.offline":
                    layout.addWidget(card)
                    continue
                buttons = QHBoxLayout()
                download = QPushButton("Download / Verify")
                download.setObjectName(f"download-{model_id}")
                download.clicked.connect(
                    lambda _checked=False, selected=model_id: controller.download_model(selected)
                )
                remove = QPushButton("Remove")
                remove.setObjectName(f"remove-{model_id}")
                remove.clicked.connect(
                    lambda _checked=False, selected=model_id: controller.remove_model(selected)
                )
                buttons.addStretch(1)
                buttons.addWidget(download)
                buttons.addWidget(remove)
                card_layout.addLayout(buttons)
                layout.addWidget(card)
                self._model_buttons[model_id] = (download, remove)
                download.setEnabled(not ready)
                remove.setEnabled(ready)
            if self._model_status is not None:
                self._model_status.setText("Model status loaded")

        def set_learned_terms(self, available: tuple[tuple[str, str, str], ...]) -> None:
            layout = self._learned_list
            if layout is None:
                return
            self._clear_layout(layout)
            if not available:
                placeholder = QLabel("No learned terms yet")
                placeholder.setObjectName("learned-terms-empty")
                layout.addWidget(placeholder)
                return
            for alias, canonical, status in available:
                layout.addWidget(QLabel(f"{alias} → {canonical} ({status})"))
                if status == "pending":
                    accept = QPushButton(f"Accept {alias}")
                    accept.clicked.connect(
                        lambda _checked=False, selected=alias: controller.set_learned_term_status(
                            selected, "active"
                        )
                    )
                    reject = QPushButton(f"Reject {alias}")
                    reject.clicked.connect(
                        lambda _checked=False, selected=alias: controller.set_learned_term_status(
                            selected, "rejected"
                        )
                    )
                    layout.addWidget(accept)
                    layout.addWidget(reject)

        @staticmethod
        def _clear_layout(layout: QVBoxLayout) -> None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()

        def closeEvent(self, event: QCloseEvent) -> None:
            if self._close_to_tray:
                event.ignore()
                self.hide()
                controller.dashboard_hidden()
                return
            event.ignore()
            controller.quit_application()

    return Dashboard()
