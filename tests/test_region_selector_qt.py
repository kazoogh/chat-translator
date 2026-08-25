from __future__ import annotations

from collections.abc import Callable

import pytest

from game_chat_translator.capture.base import CaptureError, RawFrame
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

    preview_dimensions: list[tuple[int, int]] = []

    def preview(frame: RawFrame, done: Callable[[bool, tuple[str, ...]], None]) -> None:
        preview_dimensions.append((frame.width, frame.height))
        done(True, ("Игрок: привет",))

    assert (
        launch_region_selector(calibration, retry_capture=fail_retry, request_preview=preview) == 0
    )
    application.processEvents()
    assert preview_dimensions == [(45, 35)]
    assert calibration.preview_has_likely_text is True
    assert calibration.preview_lines == ("Игрок: привет",)
    selector = next(widget for widget in application.topLevelWidgets() if widget.isVisible())
    available = application.primaryScreen().availableGeometry()
    assert selector.size() == available.size()
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


def test_selector_ignores_out_of_order_preview_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    application = QApplication.instance() or QApplication([])
    calibration = session([])
    completions: list[Callable[[bool, tuple[str, ...]], None]] = []

    def preview(_frame: RawFrame, done: Callable[[bool, tuple[str, ...]], None]) -> None:
        completions.append(done)

    launch_region_selector(calibration, request_preview=preview)
    selector = next(widget for widget in application.topLevelWidgets() if widget.isVisible())
    application.processEvents()
    calibration.move(1, 0)
    selector._request_preview()
    application.processEvents()
    assert len(completions) == 2

    completions[1](True, ("new selection",))
    application.processEvents()
    completions[0](False, ("stale selection",))
    application.processEvents()
    assert calibration.preview_has_likely_text is True
    assert calibration.preview_lines == ("new selection",)

    buttons = {button.text(): button for button in selector.findChildren(QPushButton)}
    buttons["Cancel"].click()


def test_selector_waits_for_async_calibration_commit_and_handles_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    application = QApplication.instance() or QApplication([])
    calibration = session([])
    calibration.set_preview_result(has_likely_text=True)
    completions: list[Callable[[bool], None]] = []
    committed: list[object] = []
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    def save(region: object, done: Callable[[bool], None]) -> None:
        committed.append(region)
        completions.append(done)

    finished: list[bool] = []
    launch_region_selector(calibration, request_save=save, on_finished=finished.append)
    selector = next(widget for widget in application.topLevelWidgets() if widget.isVisible())
    buttons = {button.text(): button for button in selector.findChildren(QPushButton)}
    buttons["Save"].click()
    assert not calibration.saved
    completions.pop()(False)
    application.processEvents()
    assert not calibration.saved
    assert warnings == ["Calibration storage is temporarily unavailable."]

    buttons["Save"].click()
    completions.pop()(True)
    application.processEvents()
    assert calibration.saved
    assert finished == [True]
    assert len(committed) == 2
