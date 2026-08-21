from __future__ import annotations

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import OcrFragment


def render_boxes_bgra(
    frame: RawFrame,
    fragments: tuple[OcrFragment, ...],
    *,
    color: tuple[int, int, int, int] = (255, 196, 64, 255),
) -> RawFrame:
    """Return an in-memory annotated copy; never persists the source frame."""
    if frame.pixel_format != "BGRA" or len(frame.pixels) != frame.width * frame.height * 4:
        raise ValueError("diagnostic box rendering requires a valid BGRA frame")
    output = bytearray(frame.pixels)
    for fragment in fragments:
        xs = [round(point.x) for point in fragment.polygon]
        ys = [round(point.y) for point in fragment.polygon]
        left = min(max(min(xs), 0), frame.width - 1)
        right = min(max(max(xs), left), frame.width - 1)
        top = min(max(min(ys), 0), frame.height - 1)
        bottom = min(max(max(ys), top), frame.height - 1)
        for x in range(left, right + 1):
            _set_pixel(output, frame.width, x, top, color)
            _set_pixel(output, frame.width, x, bottom, color)
        for y in range(top, bottom + 1):
            _set_pixel(output, frame.width, left, y, color)
            _set_pixel(output, frame.width, right, y, color)
    return RawFrame(frame.width, frame.height, "BGRA", bytes(output))


def _set_pixel(
    output: bytearray, width: int, x: int, y: int, color: tuple[int, int, int, int]
) -> None:
    index = (y * width + x) * 4
    output[index : index + 4] = bytes(color)
