from __future__ import annotations

from pathlib import Path
from threading import Event, Thread
from typing import cast

from game_chat_translator.classification.classifier import ClassificationDecision, MessageClassifier
from game_chat_translator.classification.pipeline import ClassificationOffer, ClassificationPipeline
from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.language.glossary import GlossaryResolver
from game_chat_translator.models import ChatLine, MessageClass, Point
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.runtime.queues import OfferResult

ROOT = Path(__file__).resolve().parents[1]


def _line(text: str, order: int) -> ChatLine:
    return ChatLine(raw_text=text, normalized_text=text, confidence=0.95, visual_order=order)


def _pipeline(*, capacity: int = 2) -> ClassificationPipeline:
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    glossary = GlossaryResolver(resources.glossary)
    return ClassificationPipeline(
        MessageClassifier(resources),
        LocalLanguageDetector(glossary),
        capacity=capacity,
        initial_generation=4,
    )


def test_pipeline_preserves_visual_order_and_unknown_visibility() -> None:
    pipeline = _pipeline()
    result = pipeline.offer_lines(
        (_line("Vasya: privet", 0), _line("unrecognized status", 1)), generation=4
    )
    assert result.status is OfferResult.ACCEPTED
    first = pipeline.take()
    second = pipeline.take()
    assert first is not None and second is not None
    assert first.visual_order == 0
    assert first.decision.message.classification is MessageClass.PLAYER_INBOUND
    assert first.decision.should_announce
    assert first.language.primary_language == "ru-Latn"
    assert second.visual_order == 1
    assert second.decision.message.classification is MessageClass.UNKNOWN
    assert not second.decision.should_announce


def test_pipeline_rejects_before_acceptance_and_never_silently_drops() -> None:
    pipeline = _pipeline(capacity=1)
    first_line = _line("Vasya: hello", 0)
    second_line = _line("Petya: privet", 1)
    assert pipeline.offer_lines((first_line,), generation=4).status is OfferResult.ACCEPTED
    assert pipeline.offer_lines((second_line,), generation=4).status is OfferResult.REJECTED_FULL
    first = pipeline.take()
    assert first is not None and first.decision.message.body == "hello"
    assert pipeline.offer_lines((second_line,), generation=4).status is OfferResult.ACCEPTED
    second = pipeline.take()
    assert second is not None and second.decision.message.body == "privet"


def test_generation_advance_purges_old_messages_and_rejects_old_work() -> None:
    pipeline = _pipeline()
    assert (
        pipeline.offer_lines((_line("Vasya: hello", 0),), generation=4).status
        is OfferResult.ACCEPTED
    )
    pipeline.advance_generation(5)
    assert pipeline.take() is None
    assert (
        pipeline.offer_lines((_line("Vasya: stale", 0),), generation=4).status
        is OfferResult.REJECTED_OBSOLETE
    )


def test_generation_advance_is_not_blocked_by_classification() -> None:
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    delegate = MessageClassifier(resources)
    started = Event()
    release = Event()

    class BlockingClassifier:
        def classify_lines(self, lines: tuple[ChatLine, ...]) -> tuple[ClassificationDecision, ...]:
            started.set()
            assert release.wait(2)
            return delegate.classify_lines(lines)

    pipeline = ClassificationPipeline(
        cast(MessageClassifier, BlockingClassifier()),
        LocalLanguageDetector(),
        initial_generation=4,
    )
    result: list[ClassificationOffer] = []
    worker = Thread(
        target=lambda: result.append(
            pipeline.offer_lines((_line("Vasya: hello", 0),), generation=4)
        )
    )
    worker.start()
    assert started.wait(2)
    pipeline.advance_generation(5)
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert [offer.status for offer in result] == [OfferResult.REJECTED_OBSOLETE]


def test_oversized_batch_makes_bounded_exactly_once_progress() -> None:
    pipeline = _pipeline(capacity=2)
    remaining = tuple(_line(f"Player{index}: hello", index) for index in range(5))
    published: list[int] = []
    while remaining:
        offered = pipeline.offer_lines(remaining, generation=4)
        assert offered.accepted_messages > 0
        if len(remaining) > 2:
            assert offered.status is OfferResult.PARTIALLY_ACCEPTED
        remaining = remaining[offered.consumed_lines :]
        while (item := pipeline.take()) is not None:
            published.append(item.visual_order)
    assert published == [0, 1, 2, 3, 4]


def test_wrapped_decision_retains_source_order_for_following_message() -> None:
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    pipeline = ClassificationPipeline(
        MessageClassifier(resources), LocalLanguageDetector(), capacity=2, initial_generation=4
    )

    def positioned(text: str, order: int, left: float) -> ChatLine:
        box = (
            Point(x=left, y=0),
            Point(x=left + 8, y=0),
            Point(x=left + 8, y=4),
            Point(x=left, y=4),
        )
        return ChatLine(
            raw_text=text,
            normalized_text=text,
            boxes=(box,),
            confidence=0.95,
            visual_order=order,
        )

    offered = pipeline.offer_lines(
        (
            positioned("Vasya: wrapped", 10, 5),
            positioned("body", 20, 20),
            positioned("Petya: hello", 30, 5),
        ),
        generation=4,
    )
    assert offered.status is OfferResult.ACCEPTED
    assert offered.consumed_lines == 3
    first = pipeline.take()
    second = pipeline.take()
    assert first is not None and second is not None
    assert [first.visual_order, second.visual_order] == [10, 30]
