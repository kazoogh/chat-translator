from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock

from game_chat_translator.classification.classifier import ClassificationDecision, MessageClassifier
from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.models import ChatLine, LanguageAnalysis
from game_chat_translator.runtime.queues import OfferResult


@dataclass(frozen=True, slots=True)
class AnalyzedMessage:
    generation: int
    visual_order: int
    decision: ClassificationDecision
    language: LanguageAnalysis


@dataclass(frozen=True, slots=True)
class ClassificationOffer:
    status: OfferResult
    accepted_messages: int
    consumed_lines: int
    total_messages: int


class ClassificationPipeline:
    """Profile-driven classification with an explicitly backpressured FIFO output."""

    def __init__(
        self,
        classifier: MessageClassifier,
        language_detector: LocalLanguageDetector,
        *,
        capacity: int = 64,
        initial_generation: int = 0,
    ) -> None:
        if capacity <= 0:
            raise ValueError("classification queue capacity must be positive")
        self._classifier = classifier
        self._language_detector = language_detector
        self._capacity = capacity
        self._generation = initial_generation
        self._items: deque[AnalyzedMessage] = deque()
        self._lock = Lock()
        self._producer_lock = Lock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def advance_generation(
        self,
        generation: int,
        *,
        classifier: MessageClassifier | None = None,
        language_detector: LocalLanguageDetector | None = None,
    ) -> None:
        with self._lock:
            if generation < self._generation:
                raise ValueError("classification generation cannot move backwards")
            self._generation = generation
            if classifier is not None:
                self._classifier = classifier
            if language_detector is not None:
                self._language_detector = language_detector
            self._items = deque(item for item in self._items if item.generation == generation)

    def offer_lines(self, lines: tuple[ChatLine, ...], *, generation: int) -> ClassificationOffer:
        with self._producer_lock:
            return self._offer_lines(lines, generation=generation)

    def _offer_lines(self, lines: tuple[ChatLine, ...], *, generation: int) -> ClassificationOffer:
        with self._lock:
            if generation != self._generation:
                return ClassificationOffer(OfferResult.REJECTED_OBSOLETE, 0, 0, 0)
            classifier = self._classifier
            language_detector = self._language_detector
        decisions = classifier.classify_lines(lines)
        with self._lock:
            if generation != self._generation:
                return ClassificationOffer(OfferResult.REJECTED_OBSOLETE, 0, 0, len(decisions))
            available = self._capacity - len(self._items)
        accepted_decisions = decisions[:available]
        analyzed = tuple(
            AnalyzedMessage(
                generation=generation,
                visual_order=decision.source_visual_order,
                decision=decision,
                language=language_detector.analyze(
                    decision.message.body,
                    additional_protected_terms=(decision.message.speaker,)
                    if decision.message.speaker
                    else (),
                ),
            )
            for decision in accepted_decisions
        )
        with self._lock:
            if generation != self._generation:
                return ClassificationOffer(OfferResult.REJECTED_OBSOLETE, 0, 0, len(decisions))
            self._items.extend(analyzed)
            consumed = sum(len(decision.source_line_ids) for decision in accepted_decisions)
            status = (
                OfferResult.ACCEPTED
                if len(accepted_decisions) == len(decisions)
                else OfferResult.PARTIALLY_ACCEPTED
                if accepted_decisions
                else OfferResult.REJECTED_FULL
            )
            return ClassificationOffer(status, len(analyzed), consumed, len(decisions))

    def take(self) -> AnalyzedMessage | None:
        with self._lock:
            return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
