from __future__ import annotations

import pytest

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.vision.preprocess import OpenCvPreprocessor, PreprocessConfig

pytestmark = pytest.mark.vision


def test_pinned_opencv_preprocessor_runs_on_bgra_input() -> None:
    frame = RawFrame(
        2,
        2,
        "BGRA",
        bytes(
            (
                0,
                0,
                255,
                255,
                0,
                255,
                0,
                255,
                255,
                0,
                0,
                255,
                255,
                255,
                255,
                255,
            )
        ),
    )

    output = OpenCvPreprocessor().process(
        frame, PreprocessConfig(scale=2, contrast=1.0, sharpen=False)
    )

    assert (output.width, output.height, output.channels) == (4, 4, 1)
    assert len(output.pixels) == 16
