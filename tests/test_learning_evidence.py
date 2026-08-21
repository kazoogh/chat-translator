from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from game_chat_translator.learning import (
    CandidateStatus,
    GlossaryLearner,
    InMemoryLearningRepository,
    LearningPolicy,
    Observation,
)


def observation(message: str, speaker: str, *, stability: float = 0.96) -> Observation:
    return Observation(
        message_id=message,
        speaker_id=speaker,
        observed_text="detik",
        proposed_canonical="Detector",
        language="tr",
        confidence=0.97,
        ocr_stability=stability,
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_activation_requires_distinct_messages_speakers_and_stable_ocr() -> None:
    repository = InMemoryLearningRepository()
    learner = GlossaryLearner(repository, existing_canonical_terms={"Detector"})

    learner.observe(observation("m1", "a", stability=0.5))
    learner.observe(observation("m2", "b", stability=0.5))
    unstable = learner.observe(observation("m3", "b", stability=0.5)).candidate
    assert unstable is not None
    assert unstable.status is CandidateStatus.PENDING
    assert "OCR" in unstable.reason

    stable_repo = InMemoryLearningRepository()
    stable = GlossaryLearner(stable_repo, existing_canonical_terms={"Detector"})
    stable.observe(observation("m1", "a"))
    duplicate = stable.observe(observation("m1", "z"))
    assert not duplicate.accepted_evidence
    stable.observe(observation("m2", "a"))
    active = stable.observe(observation("m3", "b")).candidate
    assert active is not None
    assert active.status is CandidateStatus.ACTIVE
    assert active.distinct_messages == 3
    assert active.distinct_speakers == 2


def test_new_meaning_requires_confirmation_and_rejection_is_suppressed() -> None:
    repository = InMemoryLearningRepository()
    learner = GlossaryLearner(repository)
    for index, speaker in enumerate(("a", "b", "c"), start=1):
        candidate = learner.observe(observation(f"m{index}", speaker)).candidate
    assert candidate is not None
    assert candidate.status is CandidateStatus.PENDING
    assert "confirmation" in candidate.reason

    learner.set_status("detik", CandidateStatus.REJECTED)
    suppressed = learner.observe(observation("m4", "d"))
    assert not suppressed.accepted_evidence
    assert suppressed.candidate is not None
    assert suppressed.candidate.distinct_messages == 3


def test_conflicts_block_and_excluded_shapes_never_create_candidates() -> None:
    repository = InMemoryLearningRepository()
    learner = GlossaryLearner(
        repository,
        known_aliases={"detik": "Artifact"},
        existing_canonical_terms={"Detector"},
        usernames={"PlayerOne"},
    )
    conflict = learner.observe(observation("m1", "a"))
    assert conflict.candidate is not None
    assert conflict.candidate.status is CandidateStatus.BLOCKED

    templates = (
        replace(observation("u", "a"), observed_text="PlayerOne"),
        replace(observation("v", "a"), observed_text="https://example.com/x"),
        replace(observation("n", "a"), observed_text="12345"),
        replace(observation("s", "a"), observed_text="this is an entire sentence here"),
        replace(observation("i", "a"), observed_text="salak"),
    )
    for item in templates:
        assert learner.observe(item).candidate is None


def test_pending_evidence_is_bounded() -> None:
    repository = InMemoryLearningRepository(identity_key=b"k" * 32)
    learner = GlossaryLearner(
        repository,
        policy=LearningPolicy(maximum_evidence=3),
    )
    for index in range(10):
        learner.observe(observation(f"m{index}", f"s{index}"))
    candidate = repository.get("detik")
    assert candidate is not None
    assert len(candidate.evidence) == 3
