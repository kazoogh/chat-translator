from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from game_chat_translator.learning.domain import Candidate, CandidateStatus, Evidence
from game_chat_translator.learning.repository import LearningRepository
from game_chat_translator.storage.database import Database


class SqliteLearningRepository(LearningRepository):
    """Profile-scoped persistence that stores hashes, never conversation snippets."""

    def __init__(self, database: Database, profile_id: str) -> None:
        if not profile_id.strip():
            raise ValueError("profile ID must be nonblank")
        self._database = database
        self._profile_id = profile_id
        self._ensure_identity_key()

    def get(self, normalized_alias: str) -> Candidate | None:
        row = (
            self._database.open()
            .execute(
                """
            SELECT * FROM glossary_candidates
            WHERE profile_id = ? AND observed_text = ?
            """,
                (self._profile_id, normalized_alias),
            )
            .fetchone()
        )
        return None if row is None else self._candidate(row)

    def save(self, candidate: Candidate) -> None:
        now = datetime.now(UTC).isoformat()
        first_seen = min((item.observed_at for item in candidate.evidence), default=None)
        last_seen = max((item.observed_at for item in candidate.evidence), default=None)
        candidate_id = str(
            uuid5(NAMESPACE_URL, f"gct:{self._profile_id}:{candidate.normalized_alias}")
        )
        confidence = candidate.mean_confidence
        context_hash = candidate.evidence[-1].context_hash if candidate.evidence else "0" * 64
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO glossary_candidates(
                    candidate_id, profile_id, observed_text, proposed_canonical_term,
                    language, evidence_count, context_hash, confidence, status,
                    first_seen_at, last_seen_at, display_alias, category, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, observed_text) DO UPDATE SET
                    proposed_canonical_term=excluded.proposed_canonical_term,
                    language=excluded.language,
                    evidence_count=excluded.evidence_count,
                    context_hash=excluded.context_hash,
                    confidence=excluded.confidence,
                    status=excluded.status,
                    last_seen_at=excluded.last_seen_at,
                    display_alias=excluded.display_alias,
                    category=excluded.category,
                    reason=excluded.reason
                """,
                (
                    candidate_id,
                    self._profile_id,
                    candidate.normalized_alias,
                    candidate.proposed_canonical,
                    candidate.language,
                    len(candidate.evidence),
                    context_hash,
                    confidence,
                    candidate.status.value,
                    first_seen.isoformat() if first_seen else now,
                    last_seen.isoformat() if last_seen else now,
                    candidate.display_alias,
                    candidate.category,
                    candidate.reason,
                ),
            )
            stored = connection.execute(
                """
                SELECT candidate_id FROM glossary_candidates
                WHERE profile_id = ? AND observed_text = ?
                """,
                (self._profile_id, candidate.normalized_alias),
            ).fetchone()
            stored_id = str(stored["candidate_id"])
            connection.execute("DELETE FROM glossary_evidence WHERE candidate_id = ?", (stored_id,))
            connection.executemany(
                """
                INSERT INTO glossary_evidence(
                    candidate_id, message_key, speaker_key, context_hash,
                    confidence, ocr_stability, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        stored_id,
                        evidence.message_id,
                        evidence.speaker_id,
                        evidence.context_hash,
                        evidence.confidence,
                        evidence.ocr_stability,
                        evidence.observed_at.isoformat(),
                    )
                    for evidence in candidate.evidence
                ),
            )
            if candidate.status is CandidateStatus.ACTIVE:
                connection.execute(
                    """
                    INSERT INTO learned_terms(
                        learned_term_id, profile_id, alias, canonical_term, language,
                        category, confidence, provenance, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'local_learning', ?, ?)
                    ON CONFLICT(learned_term_id) DO UPDATE SET
                        alias=excluded.alias,
                        canonical_term=excluded.canonical_term,
                        language=excluded.language,
                        category=excluded.category,
                        confidence=excluded.confidence,
                        provenance=excluded.provenance,
                        updated_at=excluded.updated_at
                    """,
                    (
                        stored_id,
                        self._profile_id,
                        candidate.display_alias,
                        candidate.proposed_canonical,
                        candidate.language,
                        candidate.category,
                        confidence,
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    "DELETE FROM learned_terms WHERE learned_term_id = ?", (stored_id,)
                )

    def list(self, status: CandidateStatus | None = None) -> tuple[Candidate, ...]:
        query = "SELECT * FROM glossary_candidates WHERE profile_id = ?"
        parameters: tuple[str, ...] = (self._profile_id,)
        if status is not None:
            query += " AND status = ?"
            parameters += (status.value,)
        query += " ORDER BY observed_text, language"
        rows = self._database.open().execute(query, parameters).fetchall()
        return tuple(self._candidate(row) for row in rows)

    def identity_digest(self, kind: str, value: str) -> str:
        row = (
            self._database.open()
            .execute("SELECT key_bytes FROM privacy_secrets WHERE name = 'learning_identity'")
            .fetchone()
        )
        if row is None:
            raise RuntimeError("learning privacy key is unavailable")
        return hmac.new(
            bytes(row["key_bytes"]), f"gct:{kind}\0{value}".encode(), hashlib.sha256
        ).hexdigest()

    def _ensure_identity_key(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO privacy_secrets(name, key_bytes, created_at)
                VALUES ('learning_identity', ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (secrets.token_bytes(32), now),
            )

    def _candidate(self, row: object) -> Candidate:
        connection = self._database.open()
        candidate_id = str(row["candidate_id"])  # type: ignore[index]
        evidence_rows = connection.execute(
            """
            SELECT * FROM glossary_evidence
            WHERE candidate_id = ? ORDER BY observed_at, message_key
            """,
            (candidate_id,),
        ).fetchall()
        evidence = tuple(
            Evidence(
                message_id=str(item["message_key"]),
                speaker_id=str(item["speaker_key"]),
                context_hash=str(item["context_hash"]),
                confidence=float(item["confidence"]),
                ocr_stability=float(item["ocr_stability"]),
                observed_at=datetime.fromisoformat(str(item["observed_at"])),
            )
            for item in evidence_rows
        )
        display_alias = str(row["display_alias"])  # type: ignore[index]
        normalized_alias = str(row["observed_text"])  # type: ignore[index]
        return Candidate(
            normalized_alias=normalized_alias,
            display_alias=display_alias or normalized_alias,
            proposed_canonical=str(row["proposed_canonical_term"]),  # type: ignore[index]
            language=str(row["language"]),  # type: ignore[index]
            category=str(row["category"]),  # type: ignore[index]
            status=CandidateStatus(str(row["status"])),  # type: ignore[index]
            evidence=evidence,
            reason=str(row["reason"]),  # type: ignore[index]
        )
