from __future__ import annotations

import importlib.metadata

import pytest


@pytest.mark.reply_native
def test_pinned_reply_native_modules_load_without_opening_a_device() -> None:
    import av
    import faster_whisper
    import sounddevice

    assert av.__version__
    assert faster_whisper.__version__ == "1.2.1"
    assert importlib.metadata.version("sounddevice") == "0.5.5"
    assert sounddevice.get_portaudio_version()[0] > 0
