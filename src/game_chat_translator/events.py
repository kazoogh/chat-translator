from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from game_chat_translator.models import FrozenModel


class EventName(StrEnum):
    FOREGROUND_WINDOW_CHANGED = "ForegroundWindowChanged"
    ACTIVE_PROFILE_RESOLVED = "ActiveProfileResolved"
    PROFILE_RESOLUTION_FAILED = "ProfileResolutionFailed"
    FRAME_CAPTURED = "FrameCaptured"
    OCR_COMPLETED = "OcrCompleted"
    PROVIDER_FAILED = "ProviderFailed"
    NEW_CHAT_LINES_DETECTED = "NewChatLinesDetected"
    MESSAGES_CLASSIFIED = "MessagesClassified"
    LANGUAGE_ANALYZED = "LanguageAnalyzed"
    TRANSLATION_COMPLETED = "TranslationCompleted"
    TRANSLATION_DEGRADED = "TranslationDegraded"
    TRANSLATION_PUBLISHED = "TranslationPublished"
    SPEECH_QUEUED = "SpeechQueued"
    SPEECH_STARTED = "SpeechStarted"
    SPEECH_COMPLETED = "SpeechCompleted"
    SPEECH_CANCELLED = "SpeechCancelled"
    SPEECH_FAILED = "SpeechFailed"
    REPLY_RECORDING_STARTED = "ReplyRecordingStarted"
    REPLY_RECORDING_STOPPED = "ReplyRecordingStopped"
    REPLY_RECORDING_CANCELLED = "ReplyRecordingCancelled"
    REPLY_TRANSCRIBED = "ReplyTranscribed"
    REPLY_TARGET_RESOLVED = "ReplyTargetResolved"
    REPLY_TARGET_AMBIGUOUS = "ReplyTargetAmbiguous"
    REPLY_TRANSLATED = "ReplyTranslated"
    REPLY_DRAFT_READY = "ReplyDraftReady"
    REPLY_COPIED = "ReplyCopied"


class DomainEvent(FrozenModel):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    created_at: datetime
    correlation_id: UUID | None = None
    name: EventName
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def aware_timestamp(self) -> DomainEvent:
        offset = self.created_at.utcoffset()
        if self.created_at.tzinfo is None or offset is None:
            raise ValueError("created_at must be timezone-aware UTC")
        if offset.total_seconds() != 0:
            raise ValueError("created_at must use UTC")
        return self


class ErrorSeverity(StrEnum):
    INFO = "info"
    RECOVERABLE = "recoverable"
    DEGRADED = "degraded"
    FATAL = "fatal"


class AppError(FrozenModel):
    code: str
    subsystem: str
    severity: ErrorSeverity
    user_message: str
    technical_detail: str = ""
    retryable: bool = False
    suggested_action: str | None = None
    correlation_id: UUID | None = None
    causal_error_code: str | None = None
