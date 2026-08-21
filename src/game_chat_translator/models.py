from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bounds(FrozenModel):
    left: int
    top: int
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class WindowIdentity(FrozenModel):
    process_id: Annotated[int, Field(ge=0)]
    executable: str
    title: str
    window_class: str
    client_bounds: Bounds
    monitor_id: str
    dpi: Annotated[int, Field(gt=0)]
    minimized: bool = False


class ProfileSource(StrEnum):
    BUNDLED = "bundled"
    COMMUNITY = "community"
    USER = "user"


class TrustState(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    USER_APPROVED = "user_approved"


class GameProfileRef(FrozenModel):
    profile_id: str
    version: int = Field(ge=1)
    source: ProfileSource
    trust_state: TrustState


class ChatRegion(FrozenModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)
    layout_id: str
    reference_client_width: int = Field(gt=0)
    reference_client_height: int = Field(gt=0)
    reference_dpi: int = Field(gt=0)

    @model_validator(mode="after")
    def inside_client(self) -> ChatRegion:
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("chat region must be contained within normalized client bounds")
        return self


class CapturedFrame(FrozenModel):
    frame_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime
    monotonic_seconds: float = Field(ge=0)
    profile_id: str
    layout_id: str
    region: ChatRegion
    pixel_format: str = "BGRA"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    pixels: bytes = Field(repr=False)

    @model_validator(mode="after")
    def aware_timestamp(self) -> CapturedFrame:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


class Point(FrozenModel):
    x: float
    y: float


class OcrFragment(FrozenModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    polygon: tuple[Point, Point, Point, Point]
    script: str
    color: str | None = None


class ChatLine(FrozenModel):
    line_id: UUID = Field(default_factory=uuid4)
    raw_text: str = Field(max_length=8192)
    normalized_text: str = Field(max_length=8192)
    boxes: tuple[tuple[Point, Point, Point, Point], ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    visual_order: int = Field(ge=0)
    colors: tuple[str, ...] = ()


class MessageClass(StrEnum):
    PLAYER_INBOUND = "player_inbound"
    PLAYER_OUTBOUND = "player_outbound"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class ClassifiedMessage(FrozenModel):
    message_id: UUID = Field(default_factory=uuid4)
    classification: MessageClass
    speaker: str | None = None
    channel: str | None = None
    body: str
    confidence: float = Field(ge=0.0, le=1.0)


class LanguageSpan(FrozenModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    language: str
    confidence: float = Field(ge=0.0, le=1.0)


class LanguageAnalysis(FrozenModel):
    primary_language: str
    spans: tuple[LanguageSpan, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    protected_terms: tuple[str, ...] = ()


class TranslationResult(FrozenModel):
    source: str
    target_language: str
    natural_text: str
    provider: str
    model_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: tuple[str, ...] = ()


class SpeechItem(FrozenModel):
    message_id: UUID
    announcement_text: str
    priority: int = 0
    expires_at: datetime | None = None


class ReplyStatus(StrEnum):
    RECORDING = "recording"
    PROCESSING = "processing"
    NEEDS_TARGET = "needs_target"
    READY = "ready"
    COPIED = "copied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplyDraft(FrozenModel):
    transcript: str
    target_speaker: str | None
    target_language: str | None
    translated_text: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    status: ReplyStatus


class GlossaryCandidateStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class GlossaryCandidate(FrozenModel):
    observed_text: str
    proposed_canonical_term: str
    language: str
    evidence_count: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    status: GlossaryCandidateStatus = GlossaryCandidateStatus.PENDING
