from __future__ import annotations

import re

from game_chat_translator.models import ClassifiedMessage, MessageClass, TranslationResult
from game_chat_translator.speech.base import SpeechJob

_PUNCTUATION = re.compile(r"([!?.,])\1{2,}")


class AnnouncementPolicy:
    """Pure inbound-only formatter; filtering occurs before queue admission."""

    def build(
        self,
        message: ClassifiedMessage,
        translation: TranslationResult,
        *,
        announce: bool = True,
        announce_own_messages: bool = False,
        is_own_message: bool = False,
    ) -> SpeechJob | None:
        if (
            not announce
            or message.classification is not MessageClass.PLAYER_INBOUND
            or (is_own_message and not announce_own_messages)
        ):
            return None
        natural = _PUNCTUATION.sub(r"\1\1", translation.natural_text).strip()
        if not natural:
            return None
        speaker = (message.speaker or "Player").strip() or "Player"
        return SpeechJob(message.message_id, f"{speaker} said: {natural}")
