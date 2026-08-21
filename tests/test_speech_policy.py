from __future__ import annotations

from game_chat_translator.models import ClassifiedMessage, MessageClass, TranslationResult
from game_chat_translator.speech import AnnouncementPolicy


def _translation(text: str = "where are you going???") -> TranslationResult:
    return TranslationResult(
        source="ты куда",
        target_language="en",
        natural_text=text,
        provider="fake",
        confidence=1,
    )


def test_policy_admits_only_inbound_and_formats_without_changing_visual_text() -> None:
    policy = AnnouncementPolicy()
    inbound = ClassifiedMessage(
        classification=MessageClass.PLAYER_INBOUND,
        speaker="Vasya",
        body="ты куда",
        confidence=1,
    )
    translation = _translation()
    job = policy.build(inbound, translation)
    assert job is not None
    assert job.message_id == inbound.message_id
    assert job.text == "Vasya said: where are you going??"
    assert translation.natural_text == "where are you going???"

    for classification in (
        MessageClass.PLAYER_OUTBOUND,
        MessageClass.SYSTEM,
        MessageClass.UNKNOWN,
    ):
        message = inbound.model_copy(update={"classification": classification})
        assert policy.build(message, translation) is None
    assert policy.build(inbound, translation, announce=False) is None
    assert policy.build(inbound, translation, is_own_message=True) is None
    assert (
        policy.build(inbound, translation, is_own_message=True, announce_own_messages=True)
        is not None
    )
