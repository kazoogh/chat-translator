from __future__ import annotations

import pytest

from game_chat_translator.reply import HoldAction, HoldKeyStateMachine


def test_hold_key_ignores_autorepeat_unrelated_and_up_without_down() -> None:
    state = HoldKeyStateMachine("V", minimum_hold_ms=180)
    assert state.key_up("v", now=0).action is HoldAction.NONE
    assert state.key_down("x", now=0).action is HoldAction.NONE
    assert state.key_down("v", now=1).action is HoldAction.START_RECORDING
    assert state.key_down("V", now=1.1).action is HoldAction.NONE
    finished = state.key_up("v", now=1.2)
    assert finished.action is HoldAction.FINISH_RECORDING
    assert finished.held_seconds == pytest.approx(0.2)


def test_short_tap_cancel_and_shutdown_are_deterministic() -> None:
    state = HoldKeyStateMachine("v", minimum_hold_ms=180)
    state.key_down("v", now=2)
    tap = state.key_up("v", now=2.1)
    assert tap.action is HoldAction.CANCEL_RECORDING and tap.reason == "accidental_tap"
    state.key_down("v", now=3)
    assert state.cancel(reason="focus_lost").reason == "focus_lost"
    state.key_down("v", now=4)
    assert state.shutdown().reason == "shutdown"
    assert state.key_down("v", now=5).action is HoldAction.NONE
    assert state.key_up("v", now=5).action is HoldAction.NONE


@pytest.mark.parametrize("timestamp", [-1, float("nan"), float("inf")])
def test_invalid_monotonic_timestamps_are_rejected(timestamp: float) -> None:
    with pytest.raises(ValueError):
        HoldKeyStateMachine("v").key_down("v", now=timestamp)
