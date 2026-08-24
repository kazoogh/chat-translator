from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from game_chat_translator.models import ReplyDraft, ReplyStatus
from game_chat_translator.reply.base import AudioBuffer
from game_chat_translator.reply.coordinator import (
    ReplyCoordinator,
    ReplyGenerations,
    ReplyIngressResult,
)
from game_chat_translator.reply.faster_whisper_stt import (
    PcmAudio,
    TranscriptionOutcome,
    TranscriptionStatus,
)
from game_chat_translator.reply.targeting import SpeakerTracker
from game_chat_translator.translation.pipeline import TranslationPipeline
from game_chat_translator.translation.router import TranslationRouter


class _Recorder:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False

    def begin(self) -> None:
        self.events.append("microphone.begin")
        self.active = True

    def finish(self) -> AudioBuffer:
        self.events.append("microphone.finish")
        self.active = False
        return AudioBuffer(b"\0\0" * 160, 16_000, 1, 1.0, 1.2)

    def cancel(self) -> None:
        self.events.append("microphone.cancel")
        self.active = False

    def close(self) -> None:
        self.events.append("microphone.close")


class _Stt:
    def __init__(self, outcome: TranscriptionOutcome, events: list[str]) -> None:
        self.outcome = outcome
        self.events = events

    def transcribe(self, audio: PcmAudio, *, cancellation: object = None) -> TranscriptionOutcome:
        del audio, cancellation
        self.events.append("stt")
        return self.outcome

    def close(self) -> None:
        self.events.append("stt.close")


class _TranslationProvider:
    provider_id = "fake"
    model_id = "fake"

    def __init__(self, events: list[str], *, confidence_text: str = "привет") -> None:
        self.events = events
        self.confidence_text = confidence_text

    def health_check(self) -> bool:
        return True

    def translate(
        self,
        request: object,
        *,
        timeout_seconds: float,
        cancellation: object = None,
    ) -> str:
        del request, timeout_seconds, cancellation
        self.events.append("translate")
        return self.confidence_text

    def close(self) -> None:
        pass


def _build(
    tmp_path: Path,
    outcome: TranscriptionOutcome,
    *,
    copy: Callable[[str], bool] | None = None,
    observe_speaker: bool = True,
    copy_after_translation: bool = True,
) -> tuple[ReplyCoordinator, list[str], list[ReplyDraft], list[str], list[str], SpeakerTracker]:
    del tmp_path
    events: list[str] = []
    drafts: list[ReplyDraft] = []
    errors: list[str] = []
    clipboard: list[str] = []
    speakers = SpeakerTracker()
    if observe_speaker:
        speakers.observe_message("Vasya", "ru", 0.98)
    provider = _TranslationProvider(events)
    pipeline = TranslationPipeline(
        TranslationRouter(provider, None),
        initial_generations=(1, 1, 1, 1, 1, 1),
    )

    def current() -> ReplyGenerations:
        profile, layout, context, glossary, model, config = pipeline.generations
        return ReplyGenerations(
            profile, layout, context, glossary, model, config, speakers.generation
        )

    def copy_text(text: str) -> bool:
        clipboard.append(text)
        return True if copy is None else copy(text)

    coordinator = ReplyCoordinator(
        hold_key="v",
        recorder_factory=lambda: _Recorder(events),
        transcription=_Stt(outcome, events),  # type: ignore[arg-type]
        speakers=speakers,
        translation=pipeline,
        generations=current,
        pause_speech=lambda paused: events.append(f"speech.pause:{paused}"),
        wait_speech_paused=lambda _timeout: events.append("speech.ack") is None,
        copy_to_clipboard=copy_text,
        publish_draft=drafts.append,
        begin_recording=lambda: events.append("lifecycle.recording") is None,
        begin_processing=lambda: events.append("lifecycle.processing"),
        finish_operation=lambda: events.append("lifecycle.finished"),
        publish_error=errors.append,
        notify_copied=lambda: events.append("toast.generic"),
        copy_after_translation=copy_after_translation,
    )
    return coordinator, events, drafts, errors, clipboard, speakers


def _complete_hold(coordinator: ReplyCoordinator) -> None:
    assert coordinator.key_down("v", 1.0) is ReplyIngressResult.ACCEPTED
    assert coordinator.key_down("v", 1.1) is ReplyIngressResult.REJECTED_BUSY
    assert coordinator.key_up("v", 1.2) is ReplyIngressResult.ACCEPTED


def _wait_for(drafts: list[ReplyDraft], status: ReplyStatus) -> None:
    deadline = time.monotonic() + 2
    while not any(item.status is status for item in drafts) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert any(item.status is status for item in drafts)


def test_success_pauses_speech_before_microphone_and_copies_once(tmp_path: Path) -> None:
    coordinator, events, drafts, errors, clipboard, _speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.COPIED)
    coordinator.close()

    assert events.index("speech.ack") < events.index("microphone.begin")
    assert events.index("microphone.finish") < events.index("stt") < events.index("translate")
    assert clipboard == ["привет"]
    assert errors == []
    assert events.count("toast.generic") == 1
    assert events.count("speech.pause:True") == 1
    assert events.count("speech.pause:False") == 1
    assert events.index("speech.pause:False") > events.index("translate")


@pytest.mark.parametrize(
    ("outcome", "observe_speaker", "expected_error"),
    [
        (
            TranscriptionOutcome(TranscriptionStatus.FAILED, error_code="STT_NO_SPEECH"),
            True,
            "STT_NO_SPEECH",
        ),
        (TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.2), True, "STT_LOW_CONFIDENCE"),
    ],
)
def test_failures_never_touch_existing_clipboard(
    tmp_path: Path,
    outcome: TranscriptionOutcome,
    observe_speaker: bool,
    expected_error: str,
) -> None:
    coordinator, events, drafts, errors, clipboard, _speakers = _build(
        tmp_path, outcome, observe_speaker=observe_speaker
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.FAILED)
    coordinator.close()
    assert clipboard == []
    assert expected_error in errors
    assert events.count("speech.pause:False") == 1


def test_missing_target_stops_before_translation_and_clipboard(tmp_path: Path) -> None:
    coordinator, events, drafts, errors, clipboard, _speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
        observe_speaker=False,
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.NEEDS_TARGET)
    coordinator.close()
    assert "translate" not in events
    assert clipboard == []
    assert errors == []


def test_user_can_select_an_exact_tracked_target_after_ambiguity(tmp_path: Path) -> None:
    coordinator, events, drafts, errors, clipboard, speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "reply to Unknown: hello", 0.96),
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.NEEDS_TARGET)
    target = speakers.candidates()[0]
    assert coordinator.select_target(target.speaker_id) is ReplyIngressResult.ACCEPTED
    _wait_for(drafts, ReplyStatus.COPIED)
    coordinator.close()
    assert clipboard == ["привет"]
    assert errors == []
    assert events.count("translate") == 1


def test_clipboard_failure_keeps_ready_draft_and_never_reports_copied(tmp_path: Path) -> None:
    coordinator, events, drafts, errors, clipboard, _speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
        copy=lambda _text: False,
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.READY)
    deadline = time.monotonic() + 1
    while not errors and time.monotonic() < deadline:
        time.sleep(0.005)
    coordinator.close()
    assert clipboard == ["привет"]
    assert drafts[-1].status is ReplyStatus.READY
    assert errors == ["CLIPBOARD_WRITE_FAILED"]
    assert "toast.generic" not in events


def test_failed_clipboard_copy_can_retry_an_edited_memory_only_draft(tmp_path: Path) -> None:
    attempts = 0

    def copy(_text: str) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts > 1

    coordinator, _events, drafts, _errors, clipboard, _speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
        copy=copy,
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.READY)
    assert coordinator.retry_copy("edited reply") is ReplyIngressResult.ACCEPTED
    _wait_for(drafts, ReplyStatus.COPIED)
    coordinator.close()
    assert clipboard == ["привет", "edited reply"]
    assert drafts[-1].translated_text == "edited reply"


def test_auto_copy_can_be_disabled_and_requires_explicit_retry(tmp_path: Path) -> None:
    coordinator, _events, drafts, _errors, clipboard, _speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
        copy_after_translation=False,
    )
    _complete_hold(coordinator)
    _wait_for(drafts, ReplyStatus.READY)
    assert clipboard == []
    assert coordinator.retry_copy("edited") is ReplyIngressResult.ACCEPTED
    _wait_for(drafts, ReplyStatus.COPIED)
    coordinator.close()
    assert clipboard == ["edited"]


def test_speaker_generation_change_cancels_before_clipboard(tmp_path: Path) -> None:
    coordinator, events, drafts, _errors, clipboard, speakers = _build(
        tmp_path,
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.96),
    )
    assert coordinator.key_down("v", 1.0) is ReplyIngressResult.ACCEPTED
    speakers.observe_message("Trader", "tr", 0.9)
    assert coordinator.key_up("v", 1.2) is ReplyIngressResult.ACCEPTED
    _wait_for(drafts, ReplyStatus.CANCELLED)
    coordinator.close()
    assert clipboard == []
    assert "translate" not in events
