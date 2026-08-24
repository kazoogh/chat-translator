from __future__ import annotations

from uuid import uuid4

import pytest

from game_chat_translator.reply import AudioBuffer, ReplyJob, ReplyTarget, Transcript


def test_domain_values_are_bounded_immutable_and_jobs_get_unique_ids() -> None:
    audio = AudioBuffer(b"\x00\x01", 16_000, 1, 1.0, 1.1)
    assert audio.pcm == b"\x00\x01"
    transcript = Transcript("meet at Forge-11", "en", 0.9)
    target = ReplyTarget(uuid4(), "Vasya", "ru", 0.95)
    first = ReplyJob(transcript, target, 1, 2, 3, 4, 5, 6)
    second = ReplyJob(transcript, target, 1, 2, 3, 4, 5, 6)
    assert first.job_id != second.job_id
    with pytest.raises(AttributeError):
        first.job_id = uuid4()  # type: ignore[misc]


@pytest.mark.parametrize(
    "audio",
    [
        AudioBuffer,
    ],
)
def test_invalid_audio_is_rejected(audio: object) -> None:
    del audio
    with pytest.raises(ValueError):
        AudioBuffer(b"", 16_000, 1, 0, 1)
    with pytest.raises(ValueError):
        AudioBuffer(b"x", 16_000, 1, 2, 1)


def test_nonfinite_confidence_and_negative_generations_are_rejected() -> None:
    with pytest.raises(ValueError):
        Transcript("hello", "en", float("nan"))
    transcript = Transcript("hello", "en", 1)
    target = ReplyTarget(uuid4(), "Player", "ru", 1)
    with pytest.raises(ValueError):
        ReplyJob(transcript, target, -1, 0, 0, 0, 0, 0)
