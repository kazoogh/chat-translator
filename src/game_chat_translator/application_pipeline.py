from __future__ import annotations

from collections import deque
from collections.abc import Callable
from uuid import UUID

from game_chat_translator.application import InboundPresentationService
from game_chat_translator.classification.pipeline import AnalyzedMessage, ClassificationPipeline
from game_chat_translator.models import CapturedFrame, MessageClass
from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.translation.pipeline import TranslationJob, TranslationPipeline
from game_chat_translator.translation.prompting import ContextMessage, TranslationRequestBuilder
from game_chat_translator.ui.event_queue import PresentedMessage
from game_chat_translator.vision.pipeline import FrameWork, OcrPipeline, TrackedLines
from game_chat_translator.vision.preprocess import PreprocessConfig


class ApplicationPipelineCoordinator:
    """Single-owner bounded bridge from calibrated frames to UI and speech publication."""

    def __init__(
        self,
        ocr: OcrPipeline,
        classification: ClassificationPipeline,
        translation: TranslationPipeline,
        presentation: InboundPresentationService,
        *,
        target_language: str = "en",
        request_builder: TranslationRequestBuilder | None = None,
        close_translation: Callable[[], None] | None = None,
        observe_speaker: Callable[[str, str, float], None] | None = None,
    ) -> None:
        self._ocr = ocr
        self._classification = classification
        self._translation = translation
        self._presentation = presentation
        self._target_language = target_language
        self._request_builder = request_builder or TranslationRequestBuilder()
        self._close_translation = close_translation or translation.close
        self._observe_speaker = observe_speaker or (lambda _speaker, _language, _confidence: None)
        self._pending_lines: TrackedLines | None = None
        self._pending_message: AnalyzedMessage | None = None
        self._accepted: dict[UUID, AnalyzedMessage] = {}
        self._context: deque[ContextMessage] = deque(maxlen=10)
        self._pending_presentation: tuple[PresentedMessage, ContextMessage] | None = None
        self._closed = False

    @property
    def translation_pipeline(self) -> TranslationPipeline:
        return self._translation

    def submit_frame(
        self, frame: CapturedFrame, preprocess: PreprocessConfig, *, generation: int
    ) -> OfferResult:
        if self._closed:
            return OfferResult.REJECTED_OBSOLETE
        return self._ocr.submit(FrameWork(frame, preprocess, generation))

    def process_once(self) -> bool:
        if self._closed:
            return False
        progressed = self._ocr.process_next() is not None
        progressed = self._move_ocr_result() or progressed
        if not self._presentation.flush_speech():
            return progressed
        if self._pending_presentation is not None:
            presented, context = self._pending_presentation
            if not self._presentation.admit_speech(presented):
                return progressed
            self._pending_presentation = None
            self._context.append(context)
            progressed = True
        progressed = self._move_classified_message() or progressed
        translated = self._translation.process_next()
        progressed = translated is not None or progressed
        while (published := self._translation.take()) is not None:
            analyzed = self._accepted.pop(published.message_id, None)
            if analyzed is None:
                continue
            message = analyzed.decision.message
            result = published.outcome.result
            announce = (
                analyzed.decision.should_announce
                and analyzed.language.confidence >= 0.55
                and result.confidence >= 0.55
            )
            outcome = self._presentation.publish_outcome(message, result, announce=announce)
            context = ContextMessage(message.speaker, message.body, result.natural_text)
            if outcome.visualized and not outcome.speech_admitted:
                self._pending_presentation = (outcome.message, context)
                return True
            if outcome.visualized:
                self._context.append(context)
            progressed = True
        return progressed

    def advance_generations(
        self,
        *,
        frame: int,
        profile: int,
        layout: int,
        context: int,
        glossary: int,
        model: int,
        config: int,
    ) -> None:
        self._ocr.advance_generation(frame)
        self._classification.advance_generation(frame)
        self._translation.advance_generations(
            profile=profile,
            layout=layout,
            context=context,
            glossary=glossary,
            model=model,
            config=config,
        )
        self._pending_lines = None
        self._pending_message = None
        self._accepted.clear()
        self._context.clear()
        self._pending_presentation = None

    def advance_frame_layout(self, *, frame: int, layout: int) -> None:
        profile, _layout, context, glossary, model, config = self._translation.generations
        self.advance_generations(
            frame=frame,
            profile=profile,
            layout=layout,
            context=context,
            glossary=glossary,
            model=model,
            config=config,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending_lines = None
        self._pending_message = None
        self._accepted.clear()
        self._context.clear()
        self._pending_presentation = None
        self._ocr.close()
        self._close_translation()

    def _move_ocr_result(self) -> bool:
        pending = self._pending_lines or self._ocr.take_result()
        if pending is None:
            return False
        offered = self._classification.offer_lines(pending.lines, generation=pending.generation)
        if offered.status is OfferResult.REJECTED_OBSOLETE:
            self._pending_lines = None
            return True
        if offered.consumed_lines < len(pending.lines):
            self._pending_lines = TrackedLines(
                pending.lines[offered.consumed_lines :], pending.generation
            )
        else:
            self._pending_lines = None
        return offered.accepted_messages > 0

    def _move_classified_message(self) -> bool:
        analyzed = self._pending_message or self._classification.take()
        if analyzed is None:
            return False
        message = analyzed.decision.message
        if message.classification is not MessageClass.PLAYER_INBOUND:
            self._pending_message = None
            self._presentation.publish(message, None, announce=False)
            return True
        profile, layout, context, glossary, model, config = self._translation.generations
        try:
            request = self._request_builder.build(
                message.body,
                source_language=analyzed.language.primary_language,
                target_language=self._target_language,
                protected_terms=analyzed.language.protected_terms,
                context=tuple(self._context),
                context_generation=context,
                glossary_generation=glossary,
                model_generation=model,
            )
        except ValueError:
            self._pending_message = None
            self._presentation.publish(message, None, announce=False)
            return True
        offered = self._translation.offer(
            TranslationJob(message.message_id, request, profile, layout, config)
        )
        if offered is OfferResult.REJECTED_FULL:
            self._pending_message = analyzed
            return False
        self._pending_message = None
        if offered is OfferResult.ACCEPTED:
            self._accepted[message.message_id] = analyzed
            if message.speaker is not None and analyzed.language.confidence >= 0.55:
                self._observe_speaker(
                    message.speaker,
                    analyzed.language.primary_language,
                    analyzed.language.confidence,
                )
        return True
