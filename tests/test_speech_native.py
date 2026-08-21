from __future__ import annotations

from pathlib import Path

import pytest

from game_chat_translator.speech import SpeechProviderError, SpeechSettings, WindowsSapiProvider

pytestmark = pytest.mark.speech_native


def test_windows_sapi_synthesizes_plain_text_to_a_local_wave(tmp_path: Path) -> None:
    import pythoncom  # type: ignore[import-untyped]
    from pywintypes import com_error  # type: ignore[import-untyped]
    from win32com.client import Dispatch  # type: ignore[import-untyped]

    output = tmp_path / "speech-smoke.wav"
    degraded = False
    pythoncom.CoInitialize()
    stream = None
    voice = None
    try:
        voice = Dispatch("SAPI.SpVoice")
        voices = voice.GetVoices()
        assert int(voices.Count) > 0
        # Hosted Windows images can expose voice tokens while leaving the default token unset.
        voice.Voice = voices.Item(0)
        stream = Dispatch("SAPI.SpFileStream")
        stream.Open(str(output), 3, False)
        voice.AudioOutputStream = stream
        voice.Rate = 0
        voice.Volume = 50
        try:
            voice.Speak("Game chat translator speech check.", 16)
        except com_error as exc:
            # Hosted Windows Server images can advertise a token whose speech data is absent.
            # SPERR_NOT_FOUND is a supported degraded state; every other COM failure is a defect.
            assert exc.excepinfo is not None
            assert exc.excepinfo[5] == -2147200966
            degraded = True
        stream.Close()
        stream = None
        if not degraded:
            voice.AudioOutputStream = None
    finally:
        if stream is not None:
            stream.Close()
        voice = None
        pythoncom.CoUninitialize()

    if degraded:
        provider = WindowsSapiProvider()
        try:
            with pytest.raises(SpeechProviderError, match="Windows speech failed"):
                provider.speak(
                    "Game chat translator speech check.",
                    SpeechSettings(),
                    cancellation=_NeverCancelled(),
                )
        finally:
            provider.close()
        return

    data = output.read_bytes()
    assert len(data) > 44
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


class _NeverCancelled:
    cancelled = False
