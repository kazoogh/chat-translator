from __future__ import annotations

import time

import pytest

from game_chat_translator.reply.hotkeys import WindowsHoldKeyObserver, WindowsShortcutObserver


def test_observer_emits_only_configured_key_edges_and_final_release() -> None:
    states = iter((0, 0x8000, 0x8000, 0, 0x8000))
    edges: list[tuple[str, str]] = []
    observer = WindowsHoldKeyObserver(
        "v",
        lambda key, _now: edges.append(("down", key)),
        lambda key, _now: edges.append(("up", key)),
        poll_seconds=0.005,
        get_key_state=lambda virtual_key: next(states),
        on_failure=lambda _code: None,
    )
    observer.start()
    deadline = time.monotonic() + 1
    while len(edges) < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    observer.close()
    assert edges == [("down", "V"), ("up", "V"), ("down", "V"), ("up", "V")]


@pytest.mark.parametrize("key", ["", "ctrl+v", "mouse1", "F13"])
def test_observer_rejects_broad_or_invalid_key_grammars(key: str) -> None:
    with pytest.raises(ValueError):
        WindowsHoldKeyObserver(key, lambda _key, _now: None, lambda _key, _now: None)


def test_observer_failure_is_fixed_code_and_close_is_idempotent() -> None:
    failures: list[str] = []
    observer = WindowsHoldKeyObserver(
        "F2",
        lambda _key, _now: None,
        lambda _key, _now: None,
        poll_seconds=0.005,
        get_key_state=lambda _key: (_ for _ in ()).throw(OSError("private device detail")),
        on_failure=failures.append,
    )
    observer.start()
    deadline = time.monotonic() + 1
    while not failures and time.monotonic() < deadline:
        time.sleep(0.005)
    observer.close()
    observer.close()
    assert failures == ["HOTKEY_OBSERVER_FAILED"]


def test_shortcuts_emit_one_rising_edge_and_observe_only_configured_keys() -> None:
    states: dict[int, int] = {}
    observed_keys: set[int] = set()
    actions: list[str] = []

    def get_state(key: int) -> int:
        observed_keys.add(key)
        return states.get(key, 0)

    observer = WindowsShortcutObserver(
        {"pause": "ctrl+shift+t", "mute": "ctrl+shift+m"},
        actions.append,
        poll_seconds=0.005,
        get_key_state=get_state,
    )
    observer.start()
    states.update({0x11: 0x8000, 0x10: 0x8000, ord("T"): 0x8000})
    deadline = time.monotonic() + 1
    while actions != ["pause"] and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.02)
    states[ord("T")] = 0
    time.sleep(0.02)
    states[ord("M")] = 0x8000
    deadline = time.monotonic() + 1
    while actions != ["pause", "mute"] and time.monotonic() < deadline:
        time.sleep(0.005)
    observer.close()
    assert actions == ["pause", "mute"]
    assert observed_keys == {0x11, 0x10, ord("T"), ord("M")}


@pytest.mark.parametrize("chord", ["v", "ctrl+ctrl+v", "win+v", "ctrl+mouse1"])
def test_shortcuts_reject_unbounded_or_invalid_chords(chord: str) -> None:
    with pytest.raises(ValueError):
        WindowsShortcutObserver({"action": chord}, lambda _action: None)
