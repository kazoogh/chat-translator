from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from game_chat_translator.learning.domain import (
    Candidate,
    CandidateStatus,
    Evidence,
    LearningDecision,
    LearningPolicy,
    Observation,
    OverlayExport,
    OverlayTerm,
    normalize_alias,
)
from game_chat_translator.learning.repository import LearningRepository
from game_chat_translator.validation.schemas import GlossaryFile

_URL = re.compile(r"(?:https?://|www\.)\S+|\b\S+\.\S{2,}(?:/\S*)?", re.IGNORECASE)
_NUMBER = re.compile(r"[+-]?(?:\d+[.,]?)+")
_ONE_OFF_INSULTS = frozenset(
    {
        "idiot",
        "moron",
        "noob",
        "сука",
        "дебил",
        "salak",
        "aptal",
    }
)


class GlossaryLearner:
    def __init__(
        self,
        repository: LearningRepository,
        *,
        known_aliases: dict[str, str] | None = None,
        existing_canonical_terms: set[str] | frozenset[str] = frozenset(),
        usernames: set[str] | frozenset[str] = frozenset(),
        policy: LearningPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._known_aliases = {
            normalize_alias(alias): canonical for alias, canonical in (known_aliases or {}).items()
        }
        self._canonicals = {normalize_alias(item) for item in existing_canonical_terms}
        self._usernames = {normalize_alias(item) for item in usernames}
        self._policy = policy or LearningPolicy()

    def observe(self, observation: Observation) -> LearningDecision:
        alias = normalize_alias(observation.observed_text)
        excluded = self._exclusion_reason(alias, observation)
        if excluded is not None:
            return LearningDecision(None, False, excluded)

        current = self._repository.get(alias)
        if current is not None and current.status in {
            CandidateStatus.ACTIVE,
            CandidateStatus.REJECTED,
            CandidateStatus.BLOCKED,
        }:
            return LearningDecision(current, False, f"suppressed {current.status.value} alias")

        canonical = observation.proposed_canonical.strip()
        known = self._known_aliases.get(alias)
        if known is not None and normalize_alias(known) != normalize_alias(canonical):
            blocked = current or self._new_candidate(observation, alias)
            blocked = replace(blocked, status=CandidateStatus.BLOCKED, reason="alias conflict")
            self._repository.save(blocked)
            return LearningDecision(blocked, False, "alias conflicts with an existing layer")

        if current is not None and normalize_alias(current.proposed_canonical) != normalize_alias(
            canonical
        ):
            blocked = replace(current, status=CandidateStatus.BLOCKED, reason="candidate conflict")
            self._repository.save(blocked)
            return LearningDecision(blocked, False, "alias has conflicting proposed meanings")

        candidate = current or self._new_candidate(observation, alias)
        message_key = self._repository.identity_digest("message", observation.message_id)
        if message_key in {item.message_id for item in candidate.evidence}:
            return LearningDecision(candidate, False, "duplicate message evidence")

        if len(candidate.evidence) >= self._policy.maximum_evidence:
            return LearningDecision(candidate, False, "candidate evidence limit reached")

        speaker_key = self._repository.identity_digest("speaker", observation.speaker_id)
        evidence = Evidence(
            message_id=message_key,
            speaker_id=speaker_key,
            context_hash=self._context_hash(message_key, speaker_key, alias),
            confidence=observation.confidence,
            ocr_stability=observation.ocr_stability,
            observed_at=observation.observed_at,
        )
        candidate = replace(candidate, evidence=(*candidate.evidence, evidence))
        candidate = self._evaluate(candidate)
        self._repository.save(candidate)
        return LearningDecision(candidate, True, candidate.reason or "evidence recorded")

    def set_status(self, alias: str, status: CandidateStatus) -> Candidate:
        normalized = normalize_alias(alias)
        candidate = self._repository.get(normalized)
        if candidate is None:
            raise KeyError(alias)
        updated = replace(candidate, status=status, reason=f"user marked {status.value}")
        self._repository.save(updated)
        return updated

    def export_overlay(self) -> OverlayExport:
        terms = tuple(
            OverlayTerm(
                canonical_english=item.proposed_canonical,
                aliases=(item.display_alias,),
                category=item.category,
            )
            for item in self._repository.list(CandidateStatus.ACTIVE)
        )
        return OverlayExport(terms=terms)

    def import_overlay(self, payload: OverlayExport | str | bytes | bytearray) -> OverlayExport:
        overlay = (
            payload if isinstance(payload, OverlayExport) else OverlayExport.from_json(payload)
        )
        for term in overlay.terms:
            for alias in term.aliases:
                normalized = normalize_alias(alias)
                known = self._known_aliases.get(normalized)
                if known is not None and normalize_alias(known) != normalize_alias(
                    term.canonical_english
                ):
                    raise ValueError(f"import alias conflicts with an existing layer: {alias!r}")
                self._repository.save(
                    Candidate(
                        normalized_alias=normalized,
                        display_alias=alias,
                        proposed_canonical=term.canonical_english,
                        language="und",
                        category=term.category,
                        status=CandidateStatus.ACTIVE,
                        reason="imported local overlay",
                    )
                )
        return self.export_overlay()

    def validated_local_glossary(self) -> GlossaryFile:
        overlay = self.export_overlay()
        return GlossaryFile.model_validate(
            {
                "schema_version": 1,
                "glossary_id": overlay.glossary_id,
                "metadata": {
                    "source": "local evidence-gated learning",
                    "notes": "User-local overlay; no raw chat evidence is exported.",
                },
                "terms": [term.model_dump(mode="json") for term in overlay.terms],
                "slang_and_profanity_notes": [],
            }
        )

    def _new_candidate(self, observation: Observation, alias: str) -> Candidate:
        return Candidate(
            normalized_alias=alias,
            display_alias=observation.observed_text.strip(),
            proposed_canonical=observation.proposed_canonical.strip(),
            language=observation.language,
            category=observation.category,
            status=CandidateStatus.PENDING,
        )

    def _evaluate(self, candidate: Candidate) -> Candidate:
        policy = self._policy
        if candidate.distinct_messages < policy.minimum_distinct_messages:
            return replace(candidate, reason="more distinct messages required")
        if candidate.distinct_speakers < policy.minimum_distinct_speakers:
            return replace(candidate, reason="more distinct speakers required")
        if candidate.mean_confidence < policy.minimum_confidence:
            return replace(candidate, reason="translation confidence below threshold")
        if candidate.mean_ocr_stability < policy.minimum_ocr_stability:
            return replace(candidate, reason="OCR stability below threshold")
        if normalize_alias(candidate.proposed_canonical) not in self._canonicals:
            return replace(candidate, reason="new canonical meaning requires confirmation")
        return replace(candidate, status=CandidateStatus.ACTIVE, reason="evidence gate passed")

    def _exclusion_reason(self, alias: str, observation: Observation) -> str | None:
        if not alias:
            return "blank aliases are excluded"
        if alias in self._usernames or alias == normalize_alias(observation.speaker_id):
            return "usernames are excluded"
        if _URL.fullmatch(alias):
            return "URLs are excluded"
        if _NUMBER.fullmatch(alias):
            return "numbers are excluded"
        if len(alias.split()) > self._policy.maximum_alias_words or any(
            punctuation in observation.observed_text for punctuation in ".!?\n"
        ):
            return "sentences are excluded"
        if alias in _ONE_OFF_INSULTS:
            return "one-off insults are excluded"
        if not observation.proposed_canonical.strip():
            return "blank canonical meanings are excluded"
        return None

    @staticmethod
    def _context_hash(message_id: str, speaker_id: str, alias: str) -> str:
        material = "\0".join((message_id, speaker_id, alias)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()
