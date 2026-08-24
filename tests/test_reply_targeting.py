from __future__ import annotations

from uuid import UUID

from game_chat_translator.reply import (
    ReplyTarget,
    SpeakerTracker,
    TargetResolutionStatus,
    parse_reply_command,
)


def _target(identity: str, name: str, language: str = "ru") -> ReplyTarget:
    return ReplyTarget(UUID(identity), name, language, 0.95)


def test_plain_reply_uses_last_inbound_and_tracker_is_bounded() -> None:
    tracker = SpeakerTracker(capacity=2, monotonic=lambda: 1.0)
    tracker.observe(_target("00000000-0000-0000-0000-00000000000a", "Vasya"))
    tracker.observe(_target("00000000-0000-0000-0000-00000000000b", "Ayşe", "tr"))
    resolution = tracker.resolve()
    assert resolution.status is TargetResolutionStatus.RESOLVED
    assert resolution.target is not None and resolution.target.speaker_id == UUID(
        "00000000-0000-0000-0000-00000000000b"
    )
    tracker.observe(_target("00000000-0000-0000-0000-00000000000c", "Mehmet", "tr"))
    assert tracker.resolve("Vasya").status is TargetResolutionStatus.NEEDS_TARGET
    assert tracker.generation == 3


def test_explicit_target_is_exact_unicode_normalized_and_never_guessed() -> None:
    tracker = SpeakerTracker(monotonic=lambda: 1.0)
    tracker.observe(_target("00000000-0000-0000-0000-00000000000a", "Ayşe", "tr"))
    assert tracker.resolve("  AYŞE ").target == _target(
        "00000000-0000-0000-0000-00000000000a", "Ayşe", "tr"
    )
    assert tracker.resolve("Ayse").status is TargetResolutionStatus.NEEDS_TARGET
    tracker.observe(_target("00000000-0000-0000-0000-00000000000b", "AYŞE", "tr"))
    ambiguous = tracker.resolve("Ayşe")
    assert ambiguous.status is TargetResolutionStatus.AMBIGUOUS
    assert {item.speaker_id for item in ambiguous.candidates} == {
        UUID("00000000-0000-0000-0000-00000000000a"),
        UUID("00000000-0000-0000-0000-00000000000b"),
    }


def test_observe_message_reuses_opaque_identity_and_expires_stale_context() -> None:
    now = [1.0]
    tracker = SpeakerTracker(maximum_age_seconds=10, monotonic=lambda: now[0])
    first = tracker.observe_message("Vasya", "ru", 0.9)
    second = tracker.observe_message(" VASYA ", "ru", 0.95)
    assert first.speaker_id == second.speaker_id
    now[0] = 12.0
    assert tracker.resolve().status is TargetResolutionStatus.NEEDS_TARGET


def test_command_parser_is_anchored_and_preserves_plain_speech() -> None:
    command = parse_reply_command(" reply to Vasya_By: meet at Forge-11 ")
    assert command.requested_target == "Vasya_By"
    assert command.body == "meet at Forge-11"
    plain = parse_reply_command("tell him: reply to Vasya: later")
    assert plain.requested_target is None
    assert plain.body == "tell him: reply to Vasya: later"
