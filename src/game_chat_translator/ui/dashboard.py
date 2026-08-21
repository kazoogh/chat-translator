from __future__ import annotations

from typing import Protocol


class DashboardController(Protocol):
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
) -> object:
    """Create the thin dashboard view without importing Qt at module import time."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import (
            QComboBox,
            QLabel,
            QMainWindow,
            QPushButton,
            QSlider,
            QTabWidget,
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
            self.setMinimumSize(720, 480)
            self._close_to_tray = close_to_tray
            self._status_label: QLabel | None = None
            self._voice_combo: QComboBox | None = None
            self._model_list: QVBoxLayout | None = None
            self._learned_list: QVBoxLayout | None = None
            tabs = QTabWidget(self)
            tabs.setObjectName("dashboard-tabs")
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
                tabs.addTab(self._page(name), name)
            self.setCentralWidget(tabs)

        def _page(self, name: str) -> QWidget:
            page = QWidget()
            page.setObjectName(f"page-{name.casefold().replace(' ', '-').replace('&', 'and')}")
            layout = QVBoxLayout(page)
            heading = QLabel(name)
            heading.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(heading)
            if name == "Status":
                self._status_label = QLabel("Starting")
                self._status_label.setObjectName("status-summary")
                self._status_label.setWordWrap(True)
                layout.addWidget(self._status_label)
            actions = {
                "Status": (("Pause / Resume", controller.toggle_pause),),
                "Capture": (("Calibrate Chat Area", controller.calibrate),),
                "Translation Models": (("Manage Models", controller.open_model_manager),),
                "History": (("Clear History", controller.clear_history),),
                "Diagnostics": (
                    ("Export Diagnostics", controller.export_diagnostics),
                    ("Licenses", controller.open_licenses),
                ),
                "Profiles": (("Learned Terms", controller.open_learned_terms),),
            }.get(name, ())
            for label, callback in actions:
                button = QPushButton(label)
                button.setObjectName("action-" + label.casefold().replace(" ", "-"))
                button.clicked.connect(callback)
                layout.addWidget(button)
            if name == "Translation Models":
                self._model_list = QVBoxLayout()
                layout.addLayout(self._model_list)
                self.set_models(models)
            if name == "Profiles":
                self._learned_list = QVBoxLayout()
                layout.addLayout(self._learned_list)
                self.set_learned_terms(learned_terms)
            if name == "Audio & Voice":
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

        def set_status(self, status: str) -> None:
            if self._status_label is not None:
                self._status_label.setText(status)

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
            for model_id, description in available:
                layout.addWidget(QLabel(description))
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
                layout.addWidget(download)
                layout.addWidget(remove)

        def set_learned_terms(self, available: tuple[tuple[str, str, str], ...]) -> None:
            layout = self._learned_list
            if layout is None:
                return
            self._clear_layout(layout)
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
