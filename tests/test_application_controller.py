from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from game_chat_translator.application import (
    ApplicationController,
    DashboardCloseAction,
    HistoryServices,
    InboundPresentationService,
    ShutdownServices,
)
from game_chat_translator.events import AppError
from game_chat_translator.lifecycle import LifecycleState
from game_chat_translator.models import ClassifiedMessage, MessageClass, TranslationResult
from game_chat_translator.settings import AppSettings
from game_chat_translator.ui.event_queue import PresentedMessage, UiEventKind, UiEventQueue


def _message(text: str = "hello") -> PresentedMessage:
    return PresentedMessage(
        uuid4(), datetime.now(UTC), MessageClass.PLAYER_INBOUND, "player", text, "привет"
    )


def test_dashboard_close_hides_but_explicit_quit_closes_once_in_contract_order() -> None:
    calls: list[str] = []
    controller = ApplicationController(
        AppSettings(),
        UiEventQueue(),
        shutdown=ShutdownServices(
            *(
                (lambda name=name: calls.append(name))
                for name in ("capture", "compute", "speech", "audio", "hotkeys", "ui", "storage")
            )
        ),
    )
    controller.start()
    assert controller.close_dashboard(tray_available=True) is DashboardCloseAction.HIDE
    assert calls == []
    assert controller.quit()
    assert not controller.quit()
    assert calls == ["capture", "compute", "speech", "audio", "hotkeys", "ui", "storage"]
    assert controller.state is LifecycleState.STOPPING


def test_present_is_exactly_once_memory_only_by_default_and_speech_is_separate() -> None:
    events = UiEventQueue()
    persisted: list[PresentedMessage] = []
    spoken: list[PresentedMessage] = []
    controller = ApplicationController(
        AppSettings(),
        events,
        history=HistoryServices(persist=lambda message, _days: persisted.append(message)),
        queue_speech=spoken.append,
    )
    controller.start()
    message = _message()
    assert controller.present(message)
    assert not controller.present(message)
    assert controller.history == (message,)
    assert persisted == []
    assert spoken == [message]
    drained = events.drain()
    assert [event.kind for event in drained].count(UiEventKind.MESSAGE) == 1


def test_history_persistence_requires_opt_in_and_clear_has_narrow_scope() -> None:
    settings = AppSettings.model_validate(
        {
            "privacy": {"persist_message_history": True, "history_retention_days": 7},
        }
    )
    calls: list[str] = []
    persisted: list[tuple[PresentedMessage, int]] = []
    controller = ApplicationController(
        settings,
        UiEventQueue(),
        history=HistoryServices(
            persist=lambda message, days: persisted.append((message, days)),
            clear_context=lambda: calls.append("context"),
            clear_translation_cache=lambda: calls.append("cache"),
            clear_pending_writes=lambda: calls.append("pending"),
            clear_persisted=lambda: calls.append("persisted"),
        ),
    )
    controller.start()
    message = _message()
    assert controller.present(message)
    assert persisted == [(message, 7)]
    controller.clear_history()
    assert controller.history == ()
    assert calls == ["context", "cache", "pending", "persisted"]


def test_visible_history_can_clear_before_background_storage_work() -> None:
    calls: list[str] = []
    controller = ApplicationController(
        AppSettings(),
        UiEventQueue(),
        history=HistoryServices(clear_persisted=lambda: calls.append("persisted")),
    )
    controller.start()
    assert controller.present(_message())
    controller.clear_visible_history()
    assert controller.history == ()
    assert calls == []
    controller.clear_history_backing()
    assert calls == ["persisted"]


def test_speech_backpressure_is_nonblocking_and_retried_before_more_acceptance() -> None:
    available = False
    spoken: list[PresentedMessage] = []

    def offer(message: PresentedMessage) -> bool:
        if not available:
            return False
        spoken.append(message)
        return True

    events = UiEventQueue()
    controller = ApplicationController(
        AppSettings(), events, queue_speech=offer, speech_backlog_limit=1
    )
    controller.start()
    first = _message("first")
    second = _message("second")
    assert controller.present(first)
    second_outcome = controller.present_with_outcome(second)
    assert second_outcome.visualized
    assert not second_outcome.speech_admitted
    displayed = [event for event in events.drain() if event.kind is UiEventKind.MESSAGE]
    assert [event.payload for event in displayed] == [first, second]
    available = True
    assert controller.flush_speech()
    assert spoken == [first]
    assert controller.admit_speech(second)
    assert spoken == [first, second]


def test_shutdown_continues_after_failure_without_exposing_exception_content() -> None:
    calls: list[str] = []

    def fail() -> None:
        calls.append("compute")
        raise RuntimeError("raw chat sentinel")

    controller = ApplicationController(
        AppSettings(),
        UiEventQueue(),
        shutdown=ShutdownServices(
            stop_capture=lambda: calls.append("capture"),
            close_compute=fail,
            close_speech=lambda: calls.append("speech"),
            close_storage=lambda: calls.append("storage"),
        ),
    )
    controller.start()
    assert controller.quit()
    assert calls == ["capture", "compute", "speech", "storage"]
    assert len(controller.shutdown_errors) == 1
    assert "sentinel" not in controller.shutdown_errors[0].model_dump_json()


def test_history_and_speech_failures_keep_visual_message_and_redact_content() -> None:
    settings = AppSettings.model_validate(
        {"privacy": {"persist_message_history": True, "history_retention_days": 7}}
    )
    events = UiEventQueue()

    def fail(*_args: object) -> None:
        raise RuntimeError("raw chat sentinel")

    controller = ApplicationController(
        settings,
        events,
        history=HistoryServices(persist=fail),
        queue_speech=fail,
    )
    controller.start()
    message = _message("raw chat sentinel")
    assert controller.present(message)
    drained = events.drain()
    assert [event.kind for event in drained].count(UiEventKind.MESSAGE) == 1
    error_payloads = [event.payload for event in drained if event.kind is UiEventKind.ERROR]
    assert len(error_payloads) == 2
    for error in error_payloads:
        assert isinstance(error, AppError)
        assert "sentinel" not in error.model_dump_json()


def test_all_classes_display_but_only_inbound_messages_enter_speech() -> None:
    events = UiEventQueue()
    spoken: list[PresentedMessage] = []
    controller = ApplicationController(AppSettings(), events, queue_speech=spoken.append)
    controller.start()
    publisher = InboundPresentationService(controller)
    for classification in MessageClass:
        message = ClassifiedMessage(
            classification=classification,
            speaker="player" if classification is MessageClass.PLAYER_INBOUND else None,
            body=classification.value,
            confidence=0.9,
        )
        result = TranslationResult(
            source=message.body,
            target_language="en",
            natural_text=f"translated {message.body}",
            provider="fixture",
            confidence=0.9,
        )
        assert publisher.publish(message, result)
    displayed = [event for event in events.drain() if event.kind is UiEventKind.MESSAGE]
    assert len(displayed) == len(MessageClass)
    assert len(spoken) == 1
    assert spoken[0].classification is MessageClass.PLAYER_INBOUND


def test_reply_lifecycle_is_only_available_while_monitoring() -> None:
    controller = ApplicationController(AppSettings(), UiEventQueue())
    controller.start()
    assert not controller.begin_reply_recording()
    controller.resume()
    assert controller.begin_reply_recording()
    assert controller.state is LifecycleState.RECORDING_REPLY
    assert not controller.begin_reply_recording()
    controller.begin_reply_processing()
    assert controller.state is LifecycleState.PROCESSING_REPLY
    controller.finish_reply()
    assert controller.state is LifecycleState.MONITORING
