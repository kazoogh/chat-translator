from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4

_MAX_AUDIO_BYTES = 32 * 1024 * 1024
_MAX_TEXT = 8_192


@dataclass(frozen=True, slots=True)
class AudioBuffer:
    pcm: bytes
    sample_rate_hz: int
    channels: int
    started_monotonic: float
    ended_monotonic: float

    def __post_init__(self) -> None:
        if not self.pcm or len(self.pcm) > _MAX_AUDIO_BYTES:
            raise ValueError("audio buffer is empty or exceeds its bound")
        if not 8_000 <= self.sample_rate_hz <= 48_000 or self.channels not in (1, 2):
            raise ValueError("audio format is unsupported")
        if (
            not math.isfinite(self.started_monotonic)
            or not math.isfinite(self.ended_monotonic)
            or self.started_monotonic < 0
            or self.ended_monotonic < self.started_monotonic
        ):
            raise ValueError("audio monotonic timestamps are invalid")


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > _MAX_TEXT:
            raise ValueError("transcript is blank or exceeds its bound")
        if not self.language.strip() or len(self.language) > 32:
            raise ValueError("transcript language is invalid")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("transcript confidence is invalid")


@dataclass(frozen=True, slots=True)
class ReplyTarget:
    speaker_id: UUID
    display_name: str
    language: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.display_name.strip() or len(self.display_name) > 200:
            raise ValueError("speaker display name is invalid")
        if not self.language.strip() or len(self.language) > 32:
            raise ValueError("target language is invalid")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("target confidence is invalid")


@dataclass(frozen=True, slots=True)
class ReplyJob:
    transcript: Transcript
    target: ReplyTarget
    profile_generation: int
    layout_generation: int
    model_generation: int
    config_generation: int
    glossary_generation: int
    speaker_generation: int
    job_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        generations = (
            self.profile_generation,
            self.layout_generation,
            self.model_generation,
            self.config_generation,
            self.glossary_generation,
            self.speaker_generation,
        )
        if any(value < 0 for value in generations):
            raise ValueError("reply generations cannot be negative")


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...


class AudioRecorder(Protocol):
    def begin(self) -> None: ...

    def finish(self) -> AudioBuffer: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class TranscriptionProvider(Protocol):
    def health_check(self) -> bool: ...

    def transcribe(
        self,
        audio: AudioBuffer,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> Transcript: ...

    def close(self) -> None: ...


class ClipboardProvider(Protocol):
    def copy(self, text: str) -> bool: ...
