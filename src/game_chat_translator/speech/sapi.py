from __future__ import annotations

import time
from typing import Any

from game_chat_translator.speech.base import (
    SpeechCancellation,
    SpeechProviderError,
    SpeechSettings,
)

_SVS_FLAGS_ASYNC = 1
_SVS_FLAGS_PURGE = 2
_SVS_FLAGS_NOT_XML = 16


class WindowsSapiProvider:
    """Lazy Windows SAPI adapter; construct and use on one speech worker thread."""

    def __init__(self, *, poll_seconds: float = 0.02) -> None:
        if poll_seconds <= 0:
            raise ValueError("SAPI polling interval must be positive")
        try:
            import pythoncom  # type: ignore[import-untyped]
            from win32com.client import Dispatch  # type: ignore[import-untyped]
        except ImportError as exc:
            raise SpeechProviderError("Windows speech support is unavailable") from exc
        self._pythoncom = pythoncom
        self._pythoncom.CoInitialize()
        try:
            self._voice: Any = Dispatch("SAPI.SpVoice")
        except Exception as exc:
            self._pythoncom.CoUninitialize()
            raise SpeechProviderError("Windows speech could not initialize") from exc
        self._poll = poll_seconds
        self._closed = False

    def voices(self) -> tuple[tuple[str, str], ...]:
        try:
            voices = self._voice.GetVoices()
            return tuple(
                (str(voices.Item(i).Id), str(voices.Item(i).GetDescription()))
                for i in range(voices.Count)
            )
        except Exception as exc:
            raise SpeechProviderError("Windows voices could not be enumerated") from exc

    def speak(
        self,
        text: str,
        settings: SpeechSettings,
        *,
        cancellation: SpeechCancellation,
    ) -> None:
        if self._closed:
            raise SpeechProviderError("Windows speech is stopped")
        try:
            self._voice.Rate = settings.rate
            self._voice.Volume = settings.volume
            if settings.voice_id is not None:
                self._select_voice(settings.voice_id)
            # SVSFIsNotXML makes untrusted chat text plain text rather than SAPI markup.
            flags = _SVS_FLAGS_ASYNC | _SVS_FLAGS_NOT_XML
            self._voice.Speak(text, flags)
            while not self._voice.WaitUntilDone(0):
                if cancellation.cancelled:
                    self.cancel()
                    return
                time.sleep(self._poll)
        except Exception as exc:
            raise SpeechProviderError("Windows speech failed") from exc

    def cancel(self) -> None:
        if not self._closed:
            self._voice.Speak("", _SVS_FLAGS_ASYNC | _SVS_FLAGS_PURGE | _SVS_FLAGS_NOT_XML)

    def close(self) -> None:
        if self._closed:
            return
        self.cancel()
        self._closed = True
        self._voice = None
        self._pythoncom.CoUninitialize()

    def _select_voice(self, voice_id: str) -> None:
        voices = self._voice.GetVoices()
        for index in range(voices.Count):
            voice = voices.Item(index)
            if str(voice.Id) == voice_id:
                self._voice.Voice = voice
                return
        raise SpeechProviderError("configured Windows voice is unavailable")
