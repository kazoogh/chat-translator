from __future__ import annotations

import pytest

from game_chat_translator.capture.base import CaptureError
from game_chat_translator.detection.region_calibrator import (
    CalibrationMetadata,
    CalibrationSession,
)
from game_chat_translator.ui.region_selector import launch_region_selector

pytestmark = pytest.mark.windows_ui


def session(saved: list[object]) -> CalibrationSession:
    metadata = CalibrationMetadata(
        profile_id="generic.default",
        layout_id="default",
        monitor_id="DISPLAY1",
        client_width=100,
        client_height=80,
        dpi=96,
    )
    instance = CalibrationSession(metadata, bytes(100 * 80 * 4), persist=saved.append)
    instance.begin_drag(5, 5)
    instance.end_drag(50, 40)
    return instance


def test_selector_uses_existing_event_loop_and_preserves_frame_on_retry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    application = QApplication.instance() or QApplication([])
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    saved: list[object] = []
    calibration = session(saved)
    original = calibration.frozen_bgra

    def fail_retry() -> bytes:
        raise CaptureError("safe synthetic retry failure")

    assert launch_region_selector(calibration, retry_capture=fail_retry) == 0
    selector = next(widget for widget in application.topLevelWidgets() if widget.isVisible())
    buttons = {button.text(): button for button in selector.findChildren(QPushButton)}
    buttons["Retry Screenshot"].click()
    assert calibration.frozen_bgra == original
    assert calibration.selection is not None
    assert warnings == ["safe synthetic retry failure"]
    buttons["Reset"].click()
    assert calibration.selection is None
    buttons["Cancel"].click()
    assert calibration.cancelled is True
    assert saved == []
    application.processEvents()
