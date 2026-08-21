from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GlossaryMetadata(DataModel):
    source: str = Field(max_length=500)
    notes: str = Field(default="", max_length=2000)


class GlossaryTerm(DataModel):
    canonical_english: str = Field(min_length=1, max_length=200)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=1000)

    @field_validator("canonical_english")
    @classmethod
    def canonical_not_blank(cls, value: str) -> str:
        if not unicodedata.normalize("NFKC", value).strip():
            raise ValueError("canonical glossary term cannot be blank")
        return value

    @field_validator("aliases")
    @classmethod
    def aliases_are_bounded_and_nonblank(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            not unicodedata.normalize("NFKC", value).strip() or len(value) > 200 for value in values
        ):
            raise ValueError("glossary aliases must contain 1 to 200 visible characters")
        return values


class SlangNote(DataModel):
    source: str = Field(max_length=500)
    meaning: str = Field(max_length=1000)
    notes: str = Field(default="", max_length=2000)


class GlossaryFile(DataModel):
    schema_version: Literal[1] = 1
    glossary_id: str = "stalzone.v1"
    metadata: GlossaryMetadata
    terms: tuple[GlossaryTerm, ...] = Field(max_length=10_000)
    slang_and_profanity_notes: tuple[SlangNote, ...] = Field(default=(), max_length=5_000)


class ProtectedTerms(DataModel):
    usernames: tuple[str, ...]
    game_terms: tuple[str, ...]


class CorpusRow(DataModel):
    source_text: str = Field(min_length=1, max_length=5000)
    detected_language: str = Field(pattern=r"^(?:[a-z]{2,3}(?:-[A-Z]{2})?|mixed/[a-z]+)$")
    natural_english_meaning: str | None
    natural_reply_translation: str | None
    slang_typo_profanity_tone_notes: str
    protected_usernames_and_game_terms: ProtectedTerms
    confidence_or_ambiguity_notes: str

    @model_validator(mode="after")
    def exactly_one_direction(self) -> CorpusRow:
        if (self.natural_english_meaning is None) == (self.natural_reply_translation is None):
            raise ValueError("corpus row must define exactly one translation direction")
        return self


class ModelEntry(DataModel):
    model_id: str = Field(pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    provider: str
    languages: tuple[str, ...] = Field(min_length=1)
    hardware_tier: Literal["cpu_low", "cpu_balanced", "gpu"]
    size_bytes: int = Field(gt=0)
    license_id: str
    source_url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundled: bool = False


class ModelManifest(DataModel):
    schema_version: Literal[1]
    models: tuple[ModelEntry, ...]
