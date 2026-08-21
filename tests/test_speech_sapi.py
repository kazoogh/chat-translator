from __future__ import annotations

import sys
from types import ModuleType

import pytest

from game_chat_translator.speech import SpeechProviderError, SpeechSettings, WindowsSapiProvider


class _Token:
    cancelled = True


class _VoiceToken:
    Id = "voice-1"

    def GetDescription(self) -> str:
        return "Fixture voice"


class _Voices:
    Count = 1

    def Item(self, index: int) -> _VoiceToken:
        assert index == 0
        return _VoiceToken()


class _Voice:
    def __init__(self) -> None:
        self.Rate = 0
        self.Volume = 0
        self.Voice = None
        self.calls: list[tuple[str, int]] = []

    def GetVoices(self) -> _Voices:
        return _Voices()

    def Speak(self, text: str, flags: int) -> None:
        self.calls.append((text, flags))

    def WaitUntilDone(self, milliseconds: int) -> bool:
        assert milliseconds == 0
        return False


def test_sapi_is_lazy_com_owned_plain_text_and_cancellable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []
    voice = _Voice()
    pythoncom = ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: events.append("init")  # type: ignore[attr-defined]
    pythoncom.CoUninitialize = lambda: events.append("uninit")  # type: ignore[attr-defined]
    win32com = ModuleType("win32com")
    client = ModuleType("win32com.client")
    client.Dispatch = lambda name: voice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)

    provider = WindowsSapiProvider()
    assert provider.voices() == (("voice-1", "Fixture voice"),)
    provider.speak(
        "<pitch>untrusted</pitch>",
        SpeechSettings(rate=3, volume=40, voice_id="voice-1"),
        cancellation=_Token(),
    )
    provider.close()

    assert events == ["init", "uninit"]
    assert voice.Rate == 3 and voice.Volume == 40
    assert voice.Voice is not None
    assert voice.calls[0] == ("<pitch>untrusted</pitch>", 17)
    assert all(text == "" and flags == 19 for text, flags in voice.calls[1:])


def test_sapi_close_releases_com_when_broken_voice_rejects_purge(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[str] = []
    voice = _Voice()

    def broken_speak(text: str, flags: int) -> None:
        raise OSError("fixture voice is unavailable")

    voice.Speak = broken_speak  # type: ignore[method-assign]
    pythoncom = ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: events.append("init")  # type: ignore[attr-defined]
    pythoncom.CoUninitialize = lambda: events.append("uninit")  # type: ignore[attr-defined]
    win32com = ModuleType("win32com")
    client = ModuleType("win32com.client")
    client.Dispatch = lambda name: voice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)

    provider = WindowsSapiProvider()
    with pytest.raises(SpeechProviderError, match="cancellation failed"):
        provider.cancel()
    provider.close()
    provider.close()

    assert events == ["init", "uninit"]
