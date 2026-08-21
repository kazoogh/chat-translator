from __future__ import annotations

import pytest

from game_chat_translator.detection.region_calibrator import (
    CalibrationError,
    CalibrationMetadata,
    CalibrationSession,
    CalibrationViewport,
    PixelRect,
    ResizeHandle,
)


def make_session(saved: list[object]) -> CalibrationSession:
    metadata = CalibrationMetadata(
        profile_id="stalzone.default",
        layout_id="windowed",
        monitor_id="primary",
        client_width=100,
        client_height=80,
        dpi=120,
    )
    pixels = bytes(index % 251 for index in range(100 * 80 * 4))
    return CalibrationSession(metadata, pixels, persist=saved.append)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ((10, 20), (70, 60), PixelRect(10, 20, 60, 40)),
        ((70, 60), (10, 20), PixelRect(10, 20, 60, 40)),
    ],
)
def test_drag_in_both_directions_and_preview(
    start: tuple[int, int], end: tuple[int, int], expected: PixelRect
) -> None:
    session = make_session([])
    session.begin_drag(*start)
    assert session.end_drag(*end) == expected
    assert len(session.preview_bgra()) == expected.width * expected.height * 4
    session.set_preview_result(has_likely_text=True, lines=("Игрок: привет",))
    assert session.preview_lines == ("Игрок: привет",)


def test_move_resize_nudge_clamp_and_save_normalized() -> None:
    saved: list[object] = []
    session = make_session(saved)
    session.begin_drag(10, 10)
    session.end_drag(60, 50)
    assert session.move(-100, 100) == PixelRect(0, 40, 50, 40)
    assert session.resize(ResizeHandle.TOP_RIGHT, 20, -20) == PixelRect(0, 20, 70, 60)
    assert session.nudge(1, 0) == PixelRect(1, 20, 70, 60)
    region = session.save()
    assert (region.x, region.y, region.width, region.height) == (0.01, 0.25, 0.7, 0.75)
    assert saved == [region]
    with pytest.raises(CalibrationError, match="closed"):
        session.reset()


def test_cancel_reset_and_no_text_confirmation_never_persist_implicitly() -> None:
    saved: list[object] = []
    session = make_session(saved)
    session.begin_drag(10, 10)
    session.end_drag(20, 20)
    session.reset()
    with pytest.raises(CalibrationError, match="empty"):
        session.save()
    session.begin_drag(5, 5)
    session.end_drag(20, 20)
    session.preview_has_likely_text = False
    with pytest.raises(CalibrationError, match="explicit confirmation"):
        session.save()
    assert saved == []
    region = session.save(confirm_no_text=True)
    assert saved == [region]

    cancelled: list[object] = []
    cancel_session = make_session(cancelled)
    cancel_session.begin_drag(5, 5)
    cancel_session.end_drag(20, 20)
    cancel_session.cancel()
    assert cancelled == []


def test_invalid_frozen_buffer_is_rejected() -> None:
    metadata = CalibrationMetadata("generic.default", "default", "primary", 10, 10, 96)
    with pytest.raises(CalibrationError, match="pixel buffer"):
        CalibrationSession(metadata, b"short", persist=lambda _: None)


def test_retry_replaces_memory_only_frame_and_resets_selection() -> None:
    session = make_session([])
    session.begin_drag(1, 1)
    session.end_drag(5, 5)
    replacement = bytes([7]) * (100 * 80 * 4)
    session.retry(replacement)
    assert session.selection is None
    assert session.frozen_bgra == replacement


def test_viewport_fits_high_dpi_and_maps_back_to_image_pixels() -> None:
    viewport = CalibrationViewport.fit(
        3840, 2160, 1920, 1040, side_panel_width=360, device_pixel_ratio=2.0
    )
    assert viewport.view_width <= 1560
    assert viewport.view_height <= 1040
    image_point = viewport.view_to_image(round(1000 * viewport.scale), round(500 * viewport.scale))
    assert abs(image_point[0] - 1000) <= 1
    assert abs(image_point[1] - 500) <= 1
