from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GlossaryMetadata(DataModel):
    source: str
    notes: str = ""


class GlossaryTerm(DataModel):
    canonical_english: str = Field(min_length=1, max_length=200)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=1000)


class SlangNote(DataModel):
    source: str
    meaning: str
    notes: str = ""


class GlossaryFile(DataModel):
    schema_version: Literal[1] = 1
    glossary_id: str = "stalzone.v1"
    metadata: GlossaryMetadata
    terms: tuple[GlossaryTerm, ...]
    slang_and_profanity_notes: tuple[SlangNote, ...] = ()


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
