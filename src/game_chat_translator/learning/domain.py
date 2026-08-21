from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_alias(value: str) -> str:
    """Return the stable identity form used for evidence and suppression."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class CandidateStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Observation:
    message_id: str
    speaker_id: str
    observed_text: str
    proposed_canonical: str
    language: str
    confidence: float
    ocr_stability: float
    category: str = "learned"
    observed_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=UTC))

    def __post_init__(self) -> None:
        if not self.message_id.strip() or not self.speaker_id.strip():
            raise ValueError("message_id and speaker_id must be nonblank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not 0.0 <= self.ocr_stability <= 1.0:
            raise ValueError("ocr_stability must be between 0 and 1")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Evidence:
    message_id: str
    speaker_id: str
    context_hash: str
    confidence: float
    ocr_stability: float
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class Candidate:
    normalized_alias: str
    display_alias: str
    proposed_canonical: str
    language: str
    category: str
    status: CandidateStatus
    evidence: tuple[Evidence, ...] = ()
    reason: str = ""

    @property
    def distinct_messages(self) -> int:
        return len({item.message_id for item in self.evidence})

    @property
    def distinct_speakers(self) -> int:
        return len({item.speaker_id for item in self.evidence})

    @property
    def mean_confidence(self) -> float:
        if not self.evidence:
            return 0.0
        return sum(item.confidence for item in self.evidence) / len(self.evidence)

    @property
    def mean_ocr_stability(self) -> float:
        if not self.evidence:
            return 0.0
        return sum(item.ocr_stability for item in self.evidence) / len(self.evidence)


@dataclass(frozen=True, slots=True)
class LearningPolicy:
    minimum_distinct_messages: int = 3
    minimum_distinct_speakers: int = 2
    minimum_confidence: float = 0.9
    minimum_ocr_stability: float = 0.9
    maximum_alias_words: int = 4
    maximum_evidence: int = 64

    def __post_init__(self) -> None:
        if (
            self.minimum_distinct_messages < 2
            or self.minimum_distinct_speakers < 2
            or not 0.0 <= self.minimum_confidence <= 1.0
            or not 0.0 <= self.minimum_ocr_stability <= 1.0
            or self.maximum_alias_words < 1
            or self.maximum_evidence < self.minimum_distinct_messages
        ):
            raise ValueError("learning policy bounds are invalid")


@dataclass(frozen=True, slots=True)
class LearningDecision:
    candidate: Candidate | None
    accepted_evidence: bool
    reason: str


class OverlayTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_english: str = Field(min_length=1, max_length=200)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="learned locally", max_length=1000)

    @field_validator("aliases")
    @classmethod
    def aliases_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len({normalize_alias(value) for value in values}) != len(values):
            raise ValueError("overlay aliases must be unique")
        return values


class OverlayExport(BaseModel):
    """Versioned, JSON-safe import/export DTO; contains no chat snippets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    glossary_id: str = "local.learned.v1"
    terms: tuple[OverlayTerm, ...] = ()

    def json_bytes(self) -> bytes:
        return self.model_dump_json(indent=2).encode("utf-8") + b"\n"

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray | Any) -> OverlayExport:
        if isinstance(payload, str | bytes | bytearray):
            return cls.model_validate_json(payload)
        return cls.model_validate(payload)
