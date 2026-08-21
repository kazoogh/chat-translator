from __future__ import annotations

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.vision.color_sampling import attach_source_colors


def test_ocr_polygon_samples_configured_color_from_unscaled_source() -> None:
    pixels = bytearray(bytes((0, 0, 0, 255)) * 16)
    for y in range(1, 3):
        for x in range(1, 3):
            offset = (y * 4 + x) * 4
            pixels[offset : offset + 4] = bytes((107, 209, 242, 255))
    frame = RawFrame(4, 4, "BGRA", bytes(pixels))
    fragment = OcrFragment(
        text="Vasya",
        confidence=0.95,
        polygon=(
            Point(x=2, y=2),
            Point(x=6, y=2),
            Point(x=6, y=6),
            Point(x=2, y=6),
        ),
        script="latin",
    )
    sampled = attach_source_colors(
        (fragment,),
        frame,
        preprocess_scale=2,
        candidate_colors=("#F2D16B", "#74C7EC"),
        tolerance=4,
    )
    assert sampled[0].color == "#F2D16B"
