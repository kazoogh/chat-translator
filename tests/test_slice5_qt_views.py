from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from game_chat_translator.ui.dashboard import create_dashboard
from game_chat_translator.ui.translation_window import TranslationRow, create_translation_window
from game_chat_translator.ui.tray import create_tray_icon

pytestmark = pytest.mark.windows_ui


@dataclass
class Controller:
    calls: list[str] = field(default_factory=list)
    geometries: list[tuple[int, int, int, int]] = field(default_factory=list)

    def toggle_pause(self) -> None:
        self.calls.append("pause")

    def calibrate(self) -> None:
        self.calls.append("calibrate")

    def clear_history(self) -> None:
        self.calls.append("clear")

    def open_model_manager(self) -> None:
        self.calls.append("models")

    def open_learned_terms(self) -> None:
        self.calls.append("terms")

    def export_diagnostics(self) -> None:
        self.calls.append("diagnostics")

    def open_licenses(self) -> None:
        self.calls.append("licenses")

    def set_speech_rate(self, rate: int) -> None:
        self.calls.append(f"rate:{rate}")

    def set_speech_volume(self, volume_percent: int) -> None:
        self.calls.append(f"volume:{volume_percent}")

    def select_speech_voice(self, voice_id: str | None) -> None:
        self.calls.append(f"voice:{voice_id}")

    def download_model(self, model_id: str) -> None:
        self.calls.append(f"download:{model_id}")

    def remove_model(self, model_id: str) -> None:
        self.calls.append(f"remove:{model_id}")

    def set_learned_term_status(self, alias: str, status: str) -> None:
        self.calls.append(f"term:{alias}:{status}")

    def dashboard_hidden(self) -> None:
        self.calls.append("hidden")

    def toggle_mute(self) -> None:
        self.calls.append("mute")

    def show_dashboard(self) -> None:
        self.calls.append("show")

    def quit_application(self) -> None:
        self.calls.append("quit")

    def translation_geometry_changed(
        self, geometry: tuple[int, int, int, int], display_id: str
    ) -> None:
        self.geometries.append(geometry)
        self.calls.append(f"display:{display_id}")


def _application(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dashboard_has_required_tabs_actions_and_closes_to_tray(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(monkeypatch)
    from PySide6.QtWidgets import QPushButton, QTabWidget

    controller = Controller()
    dashboard = create_dashboard(controller)
    dashboard.show()
    tabs = dashboard.findChild(QTabWidget, "dashboard-tabs")
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Status",
        "Capture",
        "Profiles",
        "Translation Models",
        "Audio & Voice",
        "Hotkeys",
        "History",
        "Diagnostics",
    ]
    buttons = {button.text(): button for button in dashboard.findChildren(QPushButton)}
    for label in (
        "Pause / Resume",
        "Calibrate Chat Area",
        "Learned Terms",
        "Manage Models",
        "Clear History",
        "Export Diagnostics",
        "Licenses",
    ):
        buttons[label].click()
    assert controller.calls == [
        "pause",
        "calibrate",
        "terms",
        "models",
        "clear",
        "diagnostics",
        "licenses",
    ]
    dashboard.close()
    application.processEvents()
    assert not dashboard.isVisible()
    assert controller.calls[-1] == "hidden"


def test_dashboard_without_tray_routes_close_through_explicit_quit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(monkeypatch)
    controller = Controller()
    dashboard = create_dashboard(controller, close_to_tray=False)
    dashboard.show()
    dashboard.close()
    application.processEvents()
    assert controller.calls == ["quit"]


def test_model_and_learning_actions_require_explicit_clicks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _application(monkeypatch)
    from PySide6.QtWidgets import QPushButton

    controller = Controller()
    dashboard = create_dashboard(
        controller,
        models=(("model-1", "Local model 1"),),
        learned_terms=(("alias", "Canonical", "pending"),),
    )
    assert controller.calls == []
    dashboard.findChild(QPushButton, "download-model-1").click()
    dashboard.findChild(QPushButton, "remove-model-1").click()
    buttons = {button.text(): button for button in dashboard.findChildren(QPushButton)}
    buttons["Accept alias"].click()
    buttons["Reject alias"].click()
    assert controller.calls == [
        "download:model-1",
        "remove:model-1",
        "term:alias:active",
        "term:alias:rejected",
    ]


def test_audio_controls_delegate_bounded_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _application(monkeypatch)
    from PySide6.QtWidgets import QComboBox, QSlider

    controller = Controller()
    dashboard = create_dashboard(
        controller,
        voices=(("voice-1", "Fixture Voice"),),
    )
    dashboard.findChild(QSlider, "speech-rate").setValue(250)
    dashboard.findChild(QSlider, "speech-volume").setValue(70)
    dashboard.findChild(QComboBox, "speech-voice").setCurrentIndex(1)
    assert controller.calls == ["rate:250", "volume:70", "voice:voice-1"]


def test_translation_window_is_always_on_top_bounded_and_reports_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(monkeypatch)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    controller = Controller()
    window = create_translation_window(controller, maximum_rows=2)
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    for index in range(3):
        window.append_translation(
            TranslationRow(str(index), f"p{index}", f"message {index}", f"source {index}")
        )
    application.processEvents()
    assert window.message_count == 2
    assert window.findChild(QLabel, "translation-0") is None
    window.setGeometry(20, 30, 500, 300)
    window._publish_geometry()
    assert controller.geometries[-1] == (20, 30, 500, 300)
    window.close()


def test_tray_actions_delegate_without_owning_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    _application(monkeypatch)
    controller = Controller()
    tray = create_tray_icon(controller)
    actions = {action.text(): action for action in tray.contextMenu().actions() if action.text()}
    for label in ("Pause / Resume", "Mute / Unmute", "Open Dashboard", "Quit"):
        actions[label].trigger()
    assert controller.calls == ["pause", "mute", "show", "quit"]

    tray.set_runtime_state(profile_id="stalzone.default", calibrated=True, paused=True, muted=True)
    assert "stalzone.default" in tray.toolTip()
    assert "calibrated" in tray.toolTip()
    updated = {action.text(): action for action in tray.contextMenu().actions() if action.text()}
    assert updated["Resume Monitoring"].isChecked()
    assert updated["Unmute Speech"].isChecked()
