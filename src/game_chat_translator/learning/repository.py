from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import replace
from typing import Protocol

from game_chat_translator.learning.domain import Candidate, CandidateStatus, Evidence


class LearningRepository(Protocol):
    def get(self, normalized_alias: str) -> Candidate | None: ...

    def save(self, candidate: Candidate) -> None: ...

    def list(self, status: CandidateStatus | None = None) -> tuple[Candidate, ...]: ...

    def identity_digest(self, kind: str, value: str) -> str: ...


class InMemoryLearningRepository:
    """Deterministic fake used by tests and non-persistent application wiring."""

    def __init__(self, *, identity_key: bytes | None = None) -> None:
        self._candidates: dict[str, Candidate] = {}
        self._identity_key = identity_key or secrets.token_bytes(32)

    def get(self, normalized_alias: str) -> Candidate | None:
        return self._candidates.get(normalized_alias)

    def save(self, candidate: Candidate) -> None:
        self._candidates[candidate.normalized_alias] = candidate

    def list(self, status: CandidateStatus | None = None) -> tuple[Candidate, ...]:
        candidates = tuple(self._candidates.values())
        if status is not None:
            candidates = tuple(item for item in candidates if item.status is status)
        return tuple(sorted(candidates, key=lambda item: item.normalized_alias))

    def add_evidence(self, candidate: Candidate, evidence: Evidence) -> Candidate:
        if evidence.message_id in {item.message_id for item in candidate.evidence}:
            return candidate
        updated = replace(candidate, evidence=(*candidate.evidence, evidence))
        self.save(updated)
        return updated

    def identity_digest(self, kind: str, value: str) -> str:
        return hmac.new(
            self._identity_key, f"gct:{kind}\0{value}".encode(), hashlib.sha256
        ).hexdigest()
