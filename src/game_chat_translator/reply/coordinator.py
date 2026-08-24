from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from typing import Protocol
from uuid import UUID

from game_chat_translator.models import ReplyDraft, ReplyStatus
from game_chat_translator.reply.base import AudioRecorder, ReplyTarget
from game_chat_translator.reply.faster_whisper_stt import (
    CancellationToken,
    PcmAudio,
    TranscriptionOutcome,
    TranscriptionStatus,
)
from game_chat_translator.reply.hold_key import HoldAction, HoldKeyStateMachine
from game_chat_translator.reply.targeting import (
    SpeakerTracker,
    TargetResolutionStatus,
    parse_reply_command,
)
from game_chat_translator.translation.base import TranslationCancelled, TranslationOutcome
from game_chat_translator.translation.pipeline import TranslationPipeline
from game_chat_translator.translation.prompting import TranslationRequestBuilder


@dataclass(frozen=True, slots=True)
class ReplyGenerations:
    profile: int
    layout: int
    context: int
    glossary: int
    model: int
    config: int
    speaker: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.as_tuple()):
            raise ValueError("reply generations cannot be negative")

    def as_tuple(self) -> tuple[int, int, int, int, int, int, int]:
        return (
            self.profile,
            self.layout,
            self.context,
            self.glossary,
            self.model,
            self.config,
            self.speaker,
        )


class ReplyIngressResult(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    REJECTED_BUSY = "rejected_busy"
    REJECTED_STOPPED = "rejected_stopped"


@dataclass(frozen=True, slots=True)
class _Command:
    action: HoldAction
    generations: ReplyGenerations | None = None


@dataclass(frozen=True, slots=True)
class _TargetCommand:
    speaker_id: UUID


@dataclass(frozen=True, slots=True)
class _RetryCopyCommand:
    text: str


@dataclass(frozen=True, slots=True)
class _PendingTarget:
    transcript: str
    confidence: float
    body: str
    generations: ReplyGenerations


class _TranscriptionService(Protocol):
    def transcribe(
        self, audio: PcmAudio, *, cancellation: CancellationToken | None = None
    ) -> TranscriptionOutcome: ...

    def close(self) -> None: ...


class ReplyCoordinator:
    """One-owner hold-to-talk workflow with generation-safe clipboard delivery."""

    def __init__(
        self,
        *,
        hold_key: str,
        recorder_factory: Callable[[], AudioRecorder],
        transcription: _TranscriptionService,
        speakers: SpeakerTracker,
        translation: TranslationPipeline,
        generations: Callable[[], ReplyGenerations],
        pause_speech: Callable[[bool], None],
        wait_speech_paused: Callable[[float], bool],
        copy_to_clipboard: Callable[[str], bool],
        publish_draft: Callable[[ReplyDraft], None],
        begin_recording: Callable[[], bool] = lambda: True,
        begin_processing: Callable[[], None] = lambda: None,
        finish_operation: Callable[[], None] = lambda: None,
        publish_error: Callable[[str], None] = lambda _code: None,
        notify_copied: Callable[[], None] = lambda: None,
        protected_terms: Callable[[str], tuple[str, ...]] = lambda _text: (),
        copy_after_translation: bool = True,
        minimum_hold_ms: int = 180,
        minimum_transcript_confidence: float = 0.55,
        minimum_translation_confidence: float = 0.55,
        speech_pause_timeout: float = 2.0,
    ) -> None:
        if not 0 <= minimum_transcript_confidence <= 1:
            raise ValueError("transcript confidence threshold is invalid")
        if not 0 <= minimum_translation_confidence <= 1:
            raise ValueError("translation confidence threshold is invalid")
        if speech_pause_timeout <= 0:
            raise ValueError("speech pause timeout must be positive")
        self._hold = HoldKeyStateMachine(hold_key, minimum_hold_ms=minimum_hold_ms)
        self._recorder_factory = recorder_factory
        self._transcription = transcription
        self._speakers = speakers
        self._translation = translation
        self._generations = generations
        self._pause_speech = pause_speech
        self._wait_speech_paused = wait_speech_paused
        self._copy = copy_to_clipboard
        self._publish_draft = publish_draft
        self._begin_recording = begin_recording
        self._begin_processing = begin_processing
        self._finish_operation = finish_operation
        self._publish_error = publish_error
        self._notify_copied = notify_copied
        self._protected_terms = protected_terms
        self._copy_after_translation = copy_after_translation
        self._minimum_transcript = minimum_transcript_confidence
        self._minimum_translation = minimum_translation_confidence
        self._speech_pause_timeout = speech_pause_timeout
        self._request_builder = TranslationRequestBuilder()
        self._commands: SimpleQueue[_Command | _TargetCommand | _RetryCopyCommand] = SimpleQueue()
        self._wake = Event()
        self._stop = Event()
        self._cancel = Event()
        self._cancellation = _EventCancellation(self._cancel)
        self._lock = Lock()
        self._thread: Thread | None = None
        self._busy = False
        self._draft_active = False
        self._recorder: AudioRecorder | None = None
        self._recording_generations: ReplyGenerations | None = None
        self._pending_target: _PendingTarget | None = None
        self._last_draft: ReplyDraft | None = None
        self._draft_generations: ReplyGenerations | None = None
        self._speech_paused = False

    def start(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            if self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="gct-reply", daemon=True)
            self._thread.start()

    def key_down(self, key: str, now: float) -> ReplyIngressResult:
        with self._lock:
            if self._stop.is_set():
                return ReplyIngressResult.REJECTED_STOPPED
            if self._busy or self._draft_active:
                return ReplyIngressResult.REJECTED_BUSY
            transition = self._hold.key_down(key, now=now)
            if transition.action is not HoldAction.START_RECORDING:
                return ReplyIngressResult.IGNORED
            generations = self._generations()
            self._busy = True
        self.start()
        self._commands.put(_Command(transition.action, generations))
        self._wake.set()
        return ReplyIngressResult.ACCEPTED

    def key_up(self, key: str, now: float) -> ReplyIngressResult:
        with self._lock:
            if self._stop.is_set():
                return ReplyIngressResult.REJECTED_STOPPED
            transition = self._hold.key_up(key, now=now)
        if transition.action is HoldAction.NONE:
            return ReplyIngressResult.IGNORED
        self._commands.put(_Command(transition.action))
        self._wake.set()
        return ReplyIngressResult.ACCEPTED

    def cancel(self, *, clear_draft: bool = True) -> None:
        with self._lock:
            transition = self._hold.cancel(reason="cancelled")
            self._cancel.set()
            if clear_draft:
                self._draft_active = False
                self._pending_target = None
                self._last_draft = None
                self._draft_generations = None
        if transition.action is not HoldAction.NONE:
            self._commands.put(_Command(transition.action))
        self._wake.set()

    def select_target(self, speaker_id: UUID) -> ReplyIngressResult:
        with self._lock:
            if self._stop.is_set():
                return ReplyIngressResult.REJECTED_STOPPED
            if self._busy or self._pending_target is None:
                return ReplyIngressResult.REJECTED_BUSY
            self._busy = True
        self._commands.put(_TargetCommand(speaker_id))
        self._wake.set()
        return ReplyIngressResult.ACCEPTED

    def retry_copy(self, text: str) -> ReplyIngressResult:
        rendered = text.strip()
        if not rendered or len(rendered) > 8_192:
            raise ValueError("edited reply is blank or exceeds its bound")
        with self._lock:
            if self._stop.is_set():
                return ReplyIngressResult.REJECTED_STOPPED
            if self._busy or self._last_draft is None or self._draft_generations is None:
                return ReplyIngressResult.REJECTED_BUSY
            self._busy = True
        self._commands.put(_RetryCopyCommand(rendered))
        self._wake.set()
        return ReplyIngressResult.ACCEPTED

    def clear(self) -> None:
        self.cancel(clear_draft=True)
        self._speakers.clear()

    def close(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._cancel.set()
        transition = self._hold.shutdown()
        if transition.action is not HoldAction.NONE:
            self._commands.put(_Command(transition.action))
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("reply worker did not stop")
        self._transcription.close()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    command = self._commands.get(timeout=0.05)
                except Empty:
                    continue
                if isinstance(command, _TargetCommand):
                    self._process_selected_target(command.speaker_id)
                elif isinstance(command, _RetryCopyCommand):
                    self._process_retry_copy(command.text)
                elif command.action is HoldAction.START_RECORDING:
                    self._start_recording(command.generations)
                elif command.action is HoldAction.FINISH_RECORDING:
                    self._finish_recording()
                elif command.action is HoldAction.CANCEL_RECORDING:
                    self._cancel_recording()
        finally:
            self._cancel_recording()

    def _start_recording(self, generations: ReplyGenerations | None) -> None:
        if generations is None or not self._begin_recording():
            self._finish_busy()
            return
        self._cancel.clear()
        try:
            self._pause_for_reply()
        except Exception:
            self._fail("SPEECH_PAUSE_FAILED")
            self._cancel_recording()
            return
        if not self._wait_speech_paused(self._speech_pause_timeout):
            self._fail("SPEECH_PAUSE_FAILED")
            self._cancel_recording()
            return
        try:
            recorder = self._recorder_factory()
            self._recorder = recorder
            recorder.begin()
        except Exception:
            self._fail("MICROPHONE_UNAVAILABLE")
            self._cancel_recording()
            return
        self._recording_generations = generations
        self._publish_draft(_empty_draft(ReplyStatus.RECORDING))

    def _finish_recording(self) -> None:
        recorder = self._recorder
        generations = self._recording_generations
        if recorder is None or generations is None:
            self._finish_busy()
            return
        self._begin_processing()
        self._publish_draft(_empty_draft(ReplyStatus.PROCESSING))
        try:
            audio = recorder.finish()
            self._recorder = None
            if not self._is_current(generations):
                self._cancelled()
                return
            outcome = self._transcription.transcribe(
                PcmAudio(audio.pcm, audio.sample_rate_hz, audio.channels),
                cancellation=self._cancellation,
            )
            if outcome.status is TranscriptionStatus.CANCELLED:
                self._cancelled()
                return
            if outcome.status is not TranscriptionStatus.READY:
                self._fail(outcome.error_code or "STT_PROVIDER_FAILED")
                return
            if outcome.confidence < self._minimum_transcript:
                self._fail("STT_LOW_CONFIDENCE")
                return
            if not self._is_current(generations):
                self._cancelled()
                return
            parsed = parse_reply_command(outcome.text)
            resolution = self._speakers.resolve(parsed.requested_target)
            if (
                resolution.status is not TargetResolutionStatus.RESOLVED
                or resolution.target is None
            ):
                with self._lock:
                    self._draft_active = True
                    self._pending_target = _PendingTarget(
                        outcome.text, outcome.confidence, parsed.body, generations
                    )
                self._publish_draft(
                    ReplyDraft(
                        transcript=outcome.text,
                        target_speaker=None,
                        target_language=None,
                        translated_text=None,
                        confidence=outcome.confidence,
                        status=ReplyStatus.NEEDS_TARGET,
                    )
                )
                return
            self._translate_reply(
                outcome.text,
                outcome.confidence,
                parsed.body,
                resolution.target,
                generations,
            )
        except Exception:
            self._fail("REPLY_PROCESSING_FAILED")
        finally:
            active, self._recorder = self._recorder, None
            if active is not None:
                with suppress(Exception):
                    active.cancel()
            with suppress(Exception):
                recorder.close()
            self._recording_generations = None
            self._resume_speech()
            self._finish_busy()

    def _process_selected_target(self, speaker_id: UUID) -> None:
        pending = self._pending_target
        target = self._speakers.get(speaker_id)
        if pending is None or target is None or not self._is_current(pending.generations):
            self._cancelled()
            self._finish_busy()
            return
        if not self._begin_recording():
            self._finish_busy()
            return
        self._cancel.clear()
        try:
            self._pause_for_reply()
            if not self._wait_speech_paused(self._speech_pause_timeout):
                self._publish_error("SPEECH_PAUSE_FAILED")
                return
            self._begin_processing()
            self._translate_reply(
                pending.transcript,
                pending.confidence,
                pending.body,
                target,
                pending.generations,
            )
        except Exception:
            self._fail("REPLY_PROCESSING_FAILED")
        finally:
            self._resume_speech()
            self._finish_busy()

    def _translate_reply(
        self,
        transcript: str,
        transcript_confidence: float,
        body: str,
        target: ReplyTarget,
        generations: ReplyGenerations,
    ) -> None:
        if target.confidence < self._minimum_transcript or target.language == "unknown":
            self._fail("REPLY_TARGET_UNCERTAIN")
            return
        request = self._request_builder.build(
            body,
            source_language="en",
            target_language=target.language,
            protected_terms=self._protected_terms(body),
            context_generation=generations.context,
            glossary_generation=generations.glossary,
            model_generation=generations.model,
        )
        try:
            translated = self._translation.translate_direct(
                request,
                profile_generation=generations.profile,
                layout_generation=generations.layout,
                config_generation=generations.config,
                cancellation=self._cancellation,
            )
        except TranslationCancelled:
            self._cancelled()
            return
        if not self._translation_is_safe(translated) or not self._is_current(generations):
            self._fail("REPLY_TRANSLATION_UNCERTAIN")
            return
        draft = ReplyDraft(
            transcript=transcript,
            target_speaker=target.display_name,
            target_language=target.language,
            translated_text=translated.result.natural_text,
            confidence=min(transcript_confidence, target.confidence, translated.result.confidence),
            status=ReplyStatus.READY,
        )
        with self._lock:
            self._draft_active = True
            self._pending_target = None
            self._last_draft = draft
            self._draft_generations = generations
        self._publish_draft(draft)
        if not self._copy_after_translation:
            return
        if not self._is_current(generations) or self._cancel.is_set():
            self._cancelled()
            return
        try:
            copied = self._copy(translated.result.natural_text)
        except Exception:
            copied = False
        if not copied:
            self._publish_error("CLIPBOARD_WRITE_FAILED")
            return
        self._publish_draft(draft.model_copy(update={"status": ReplyStatus.COPIED}))
        self._notify_copied()

    def _process_retry_copy(self, text: str) -> None:
        draft = self._last_draft
        generations = self._draft_generations
        if draft is None or generations is None or not self._is_current(generations):
            self._cancelled()
            self._finish_busy()
            return
        edited = draft.model_copy(update={"translated_text": text, "status": ReplyStatus.READY})
        with self._lock:
            self._last_draft = edited
        self._publish_draft(edited)
        try:
            copied = self._copy(text)
        except Exception:
            copied = False
        if copied:
            copied_draft = edited.model_copy(update={"status": ReplyStatus.COPIED})
            with self._lock:
                self._last_draft = copied_draft
            self._publish_draft(copied_draft)
            self._notify_copied()
        else:
            self._publish_error("CLIPBOARD_WRITE_FAILED")
        self._finish_busy()

    def _cancel_recording(self) -> None:
        recorder, self._recorder = self._recorder, None
        if recorder is not None:
            with suppress(Exception):
                recorder.cancel()
            with suppress(Exception):
                recorder.close()
        self._recording_generations = None
        self._resume_speech()
        self._finish_busy()

    def _fail(self, code: str) -> None:
        self._publish_error(code)
        self._publish_draft(_empty_draft(ReplyStatus.FAILED))

    def _cancelled(self) -> None:
        with self._lock:
            self._draft_active = False
            self._pending_target = None
            self._last_draft = None
            self._draft_generations = None
        self._publish_draft(_empty_draft(ReplyStatus.CANCELLED))

    def _resume_speech(self) -> None:
        with self._lock:
            if not self._speech_paused:
                return
            self._speech_paused = False
        with suppress(Exception):
            self._pause_speech(False)

    def _pause_for_reply(self) -> None:
        self._pause_speech(True)
        with self._lock:
            self._speech_paused = True

    def _finish_busy(self) -> None:
        with self._lock:
            was_busy, self._busy = self._busy, False
        if was_busy:
            with suppress(Exception):
                self._finish_operation()

    def _is_current(self, expected: ReplyGenerations) -> bool:
        return not self._cancel.is_set() and self._generations() == expected

    def _translation_is_safe(self, outcome: TranslationOutcome) -> bool:
        return (
            not outcome.degraded
            and outcome.result.confidence >= self._minimum_translation
            and bool(outcome.result.natural_text.strip())
        )


class _EventCancellation:
    def __init__(self, event: Event) -> None:
        self._event = event

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def _empty_draft(status: ReplyStatus) -> ReplyDraft:
    return ReplyDraft(
        transcript="",
        target_speaker=None,
        target_language=None,
        translated_text=None,
        confidence=0,
        status=status,
    )
