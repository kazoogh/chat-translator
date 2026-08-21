from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.speech_native


def test_windows_sapi_synthesizes_plain_text_to_a_local_wave(tmp_path: Path) -> None:
    import pythoncom  # type: ignore[import-untyped]
    from win32com.client import Dispatch  # type: ignore[import-untyped]

    output = tmp_path / "speech-smoke.wav"
    pythoncom.CoInitialize()
    stream = None
    voice = None
    try:
        voice = Dispatch("SAPI.SpVoice")
        assert int(voice.GetVoices().Count) > 0
        stream = Dispatch("SAPI.SpFileStream")
        stream.Open(str(output), 3, False)
        voice.AudioOutputStream = stream
        voice.Rate = 0
        voice.Volume = 50
        voice.Speak("Game chat translator speech check.", 16)
        stream.Close()
        stream = None
        voice.AudioOutputStream = None
    finally:
        if stream is not None:
            stream.Close()
        voice = None
        pythoncom.CoUninitialize()

    data = output.read_bytes()
    assert len(data) > 44
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
