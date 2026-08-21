from __future__ import annotations

from game_chat_translator.models import OcrFragment
from game_chat_translator.vision.line_grouping import (
    comparison_form,
    group_fragments,
    normalize_line,
    rectangle_polygon,
)


def _fragment(text: str, left: float, top: float, *, confidence: float = 0.9) -> OcrFragment:
    return OcrFragment(
        text=text,
        confidence=confidence,
        polygon=rectangle_polygon(left, top, left + 30, top + 10),
        script="mixed",
    )


def test_group_fragments_orders_shuffled_polygons_and_preserves_display_text() -> None:
    fragments = (
        _fragment("Второй", 0, 30),
        _fragment("!", 70, 10),
        _fragment("Привет", 0, 10),
        _fragment("мир", 38, 10),
        _fragment("ignored", 0, 50, confidence=0.1),
    )

    lines = group_fragments(fragments)

    assert [line.raw_text for line in lines] == ["Привет мир!", "Второй"]
    assert [line.visual_order for line in lines] == [0, 1]
    assert len(lines[0].boxes) == 3


def test_comparison_normalization_does_not_replace_display_normalization() -> None:
    assert normalize_line("[  Player ]  wow!!!!") == "[Player] wow!!!!"
    assert comparison_form("WOW!!!!!") == "wow!!"
