from __future__ import annotations

from dataclasses import dataclass

from game_chat_translator.models import ChatLine
from game_chat_translator.vision.line_tracker import LineTracker


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _line(text: str, order: int) -> ChatLine:
    return ChatLine(raw_text=text, normalized_text=text, confidence=0.9, visual_order=order)


def test_static_and_scrolling_lines_emit_only_new_content() -> None:
    clock = FakeClock()
    tracker = LineTracker(clock=clock)
    first = (_line("alpha", 0), _line("beta", 1), _line("gamma", 2))

    assert tracker.accept(first, generation=1) == first
    assert tracker.accept(first, generation=1) == ()
    scrolled = (_line("beta", 0), _line("gamma", 1), _line("delta", 2))
    assert [line.raw_text for line in tracker.accept(scrolled, generation=1)] == ["delta"]


def test_minor_ocr_jitter_is_not_reannounced() -> None:
    tracker = LineTracker(similarity_threshold=0.8, clock=FakeClock())
    tracker.accept((_line("Player: hello!!!", 0),), generation=2)
    assert tracker.accept((_line("Player : hello!!!!", 0),), generation=2) == ()


def test_expiry_allows_a_legitimate_identical_message_again() -> None:
    clock = FakeClock()
    tracker = LineTracker(expiry_seconds=5.0, clock=clock)
    line = _line("same message", 0)
    assert tracker.accept((line,), generation=3)
    tracker.accept((), generation=3)
    clock.now = 4.9
    assert tracker.accept((line,), generation=3) == ()
    tracker.accept((), generation=3)
    clock.now = 5.0
    assert tracker.accept((line,), generation=3) == (line,)


def test_simultaneous_duplicate_is_an_occurrence_not_a_permanent_dedupe() -> None:
    tracker = LineTracker(clock=FakeClock())
    first = _line("trade?", 0)
    second = _line("trade?", 1)
    assert tracker.accept((first,), generation=4) == (first,)
    assert tracker.accept((first, second), generation=4) == (second,)


def test_generation_change_resets_history_and_recent_history_is_bounded() -> None:
    tracker = LineTracker(max_recent=2, clock=FakeClock())
    for index in range(3):
        tracker.accept((_line(f"line-{index}", index),), generation=5)
    assert tracker.recent_size == 2
    repeated = _line("line-2", 0)
    assert tracker.accept((repeated,), generation=6) == (repeated,)


def test_similar_but_meaningfully_different_trade_messages_both_emit() -> None:
    tracker = LineTracker(clock=FakeClock())
    old = _line("Trader: selling 100 medkits at North Station", 0)
    new = _line("Trader: selling 200 medkits at South Station", 0)
    assert tracker.accept((old,), generation=7) == (old,)
    tracker.accept((), generation=7)
    assert tracker.accept((new,), generation=7) == (new,)


def test_order_alignment_with_duplicate_and_middle_insertion_is_deterministic() -> None:
    tracker = LineTracker(clock=FakeClock())
    first = (_line("same", 0), _line("middle", 1), _line("same", 2))
    tracker.accept(first, generation=8)
    inserted = (
        _line("same", 0),
        _line("new insertion", 1),
        _line("middle", 2),
        _line("same", 3),
    )
    assert [line.raw_text for line in tracker.accept(inserted, generation=8)] == ["new insertion"]
