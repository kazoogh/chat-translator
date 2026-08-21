from __future__ import annotations

import pytest

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.profiles.schema import GameProfile
from game_chat_translator.vision.diagnostic_preview import render_boxes_bgra
from game_chat_translator.vision.preprocess import PreprocessConfig, ReferencePreprocessor


def test_reference_preprocessor_converts_masks_and_scales_bgra() -> None:
    frame = RawFrame(
        width=2,
        height=1,
        pixel_format="BGRA",
        pixels=bytes((0, 0, 255, 255, 255, 0, 0, 255)),
    )

    output = ReferencePreprocessor().process(
        frame,
        PreprocessConfig(scale=2, contrast=1.0, sharpen=False, text_colors=("#FF0000",)),
    )

    assert (output.width, output.height, output.channels) == (4, 2, 1)
    assert output.pixels == bytes((76, 76, 0, 0, 76, 76, 0, 0))


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (PreprocessConfig(scale=1), None),
    ],
)
def test_reference_preprocessor_rejects_invalid_buffer(
    config: PreprocessConfig, message: str | None
) -> None:
    del message
    with pytest.raises(ValueError, match="buffer length"):
        ReferencePreprocessor().process(RawFrame(2, 2, "BGRA", b"short"), config)


def test_preprocess_config_rejects_invalid_color() -> None:
    with pytest.raises(ValueError, match="RRGGBB"):
        PreprocessConfig(text_colors=("red",))


def test_preprocess_config_is_driven_by_validated_profile_data() -> None:
    profile = GameProfile.model_validate(
        {
            "schema_version": 1,
            "profile_id": "test.game",
            "version": 1,
            "display_name": "Test",
            "preprocess": {
                "scale": 3,
                "contrast": 1.5,
                "sharpen": False,
                "text_colors": ["#ABCDEF"],
            },
        }
    )
    assert PreprocessConfig.from_profile(profile) == PreprocessConfig(
        scale=3, contrast=1.5, sharpen=False, text_colors=("#ABCDEF",)
    )

    with pytest.raises(ValueError, match="RRGGBB"):
        GameProfile.model_validate(
            {
                "schema_version": 1,
                "profile_id": "test.bad",
                "version": 1,
                "display_name": "Bad",
                "preprocess": {"text_colors": ["red"]},
            }
        )


def test_diagnostic_box_preview_is_an_in_memory_copy() -> None:
    source = RawFrame(3, 3, "BGRA", bytes(3 * 3 * 4))
    fragment = OcrFragment(
        text="Привет",
        confidence=0.9,
        polygon=(Point(x=0, y=0), Point(x=2, y=0), Point(x=2, y=2), Point(x=0, y=2)),
        script="cyrillic",
    )

    preview = render_boxes_bgra(source, (fragment,))

    assert source.pixels == bytes(3 * 3 * 4)
    assert preview.pixels != source.pixels
