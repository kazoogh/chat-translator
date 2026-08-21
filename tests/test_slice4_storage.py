from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from game_chat_translator.learning import CandidateStatus, GlossaryLearner, Observation
from game_chat_translator.storage.database import Database
from game_chat_translator.storage.learning_repository import SqliteLearningRepository


def _observation(message: str, speaker: str) -> Observation:
    return Observation(
        message_id=message,
        speaker_id=speaker,
        observed_text="İstanbul önbelleği",
        proposed_canonical="Istanbul Cache",
        language="tr",
        confidence=0.98,
        ocr_stability=0.97,
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_learning_survives_database_restart_and_activates_overlay(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with Database(path) as database:
        learner = GlossaryLearner(
            SqliteLearningRepository(database, "stalzone.default"),
            existing_canonical_terms={"Istanbul Cache"},
        )
        learner.observe(_observation("m1", "ali"))
        learner.observe(_observation("m2", "ayse"))
        active = learner.observe(_observation("m3", "mehmet")).candidate
        assert active is not None and active.status is CandidateStatus.ACTIVE

    with Database(path) as database:
        repository = SqliteLearningRepository(database, "stalzone.default")
        restored = repository.list(CandidateStatus.ACTIVE)
        assert restored[0].display_alias == "İstanbul önbelleği"
        assert restored[0].distinct_messages == 3
        assert GlossaryLearner(repository).export_overlay().terms[0].aliases == (
            "İstanbul önbelleği",
        )
        assert database.open().execute("SELECT COUNT(*) FROM learned_terms").fetchone()[0] == 1


def test_candidate_and_evidence_save_is_atomic(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        repository = SqliteLearningRepository(database, "stalzone.default")
        learner = GlossaryLearner(repository, existing_canonical_terms={"Istanbul Cache"})
        learner.observe(_observation("m1", "ali"))
        database.open().execute(
            """
            CREATE TRIGGER reject_second_evidence BEFORE INSERT ON glossary_evidence
            WHEN (SELECT COUNT(*) FROM glossary_evidence
                  WHERE candidate_id = NEW.candidate_id) >= 1
            BEGIN SELECT RAISE(ABORT, 'synthetic'); END
            """
        )
        try:
            learner.observe(_observation("m2", "ayse"))
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("synthetic storage failure did not propagate")
        assert repository.get("i̇stanbul önbelleği").distinct_messages == 1  # type: ignore[union-attr]


def test_persisted_identity_keys_are_install_specific_hmacs(tmp_path: Path) -> None:
    digests: list[tuple[str, str]] = []
    for index in range(2):
        with Database(tmp_path / f"state-{index}.sqlite3") as database:
            repository = SqliteLearningRepository(database, "stalzone.default")
            GlossaryLearner(repository).observe(_observation("common-message", "common-user"))
            row = (
                database.open()
                .execute("SELECT message_key, speaker_key FROM glossary_evidence")
                .fetchone()
            )
            digests.append((str(row["message_key"]), str(row["speaker_key"])))
            assert "common" not in digests[-1][0]
            assert "common" not in digests[-1][1]
    assert digests[0] != digests[1]
