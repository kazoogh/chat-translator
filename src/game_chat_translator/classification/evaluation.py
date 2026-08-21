from __future__ import annotations

import hashlib
from dataclasses import dataclass

from game_chat_translator.classification.classifier import MessageClassifier
from game_chat_translator.models import ChatLine, MessageClass


@dataclass(frozen=True, slots=True)
class ClassificationFixture:
    fixture_id: str
    text: str
    expected: MessageClass
    confidence: float = 0.95


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    player_recall: float
    false_announcement_rate: float
    inbound_total: int
    silent_total: int
    confusion: dict[tuple[MessageClass, MessageClass], int]


def held_out(
    fixtures: tuple[ClassificationFixture, ...], *, bucket: int = 0
) -> tuple[ClassificationFixture, ...]:
    if not 0 <= bucket < 5:
        raise ValueError("held-out bucket must be between zero and four")
    return tuple(
        fixture
        for fixture in fixtures
        if hashlib.sha256(fixture.fixture_id.encode("utf-8")).digest()[0] % 5 == bucket
    )


def evaluate(
    classifier: MessageClassifier, fixtures: tuple[ClassificationFixture, ...]
) -> ClassificationMetrics:
    confusion: dict[tuple[MessageClass, MessageClass], int] = {}
    inbound_total = 0
    inbound_correct = 0
    silent_total = 0
    false_announcements = 0
    for fixture in fixtures:
        decision = classifier.classify(
            ChatLine(
                raw_text=fixture.text,
                normalized_text=fixture.text,
                confidence=fixture.confidence,
                visual_order=0,
            )
        )
        actual = decision.message.classification
        confusion[(fixture.expected, actual)] = confusion.get((fixture.expected, actual), 0) + 1
        if fixture.expected is MessageClass.PLAYER_INBOUND:
            inbound_total += 1
            inbound_correct += int(actual is MessageClass.PLAYER_INBOUND)
        else:
            silent_total += 1
            false_announcements += int(decision.should_announce)
    return ClassificationMetrics(
        player_recall=inbound_correct / inbound_total if inbound_total else 0.0,
        false_announcement_rate=false_announcements / silent_total if silent_total else 0.0,
        inbound_total=inbound_total,
        silent_total=silent_total,
        confusion=confusion,
    )
