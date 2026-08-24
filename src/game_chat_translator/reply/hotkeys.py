from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from contextlib import suppress
from functools import lru_cache
from threading import Event, Lock, Thread
from typing import Any


class HotkeyObserverError(RuntimeError):
    """Safe failure from the observation-only configured-key worker."""


class WindowsHoldKeyObserver:
    """Observe down/up edges for exactly one configured virtual key without suppression."""

    def __init__(
        self,
        key: str,
        on_down: Callable[[str, float], None],
        on_up: Callable[[str, float], None],
        *,
        poll_seconds: float = 0.01,
        monotonic: Callable[[], float] = time.monotonic,
        get_key_state: Callable[[int], int] | None = None,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        self._key = _normalize_key(key)
        self._virtual_key = _virtual_key(self._key)
        if not 0.005 <= poll_seconds <= 0.1:
            raise ValueError("hotkey poll interval is invalid")
        self._on_down = on_down
        self._on_up = on_up
        self._poll_seconds = poll_seconds
        self._monotonic = monotonic
        self._get_key_state = get_key_state
        self._on_failure = on_failure or (lambda _code: None)
        self._stop = Event()
        self._wake = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._stop.is_set():
                raise HotkeyObserverError("HOTKEY_OBSERVER_CLOSED")
            if self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="gct-hold-key", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise HotkeyObserverError("HOTKEY_OBSERVER_STOP_FAILED")

    def _run(self) -> None:
        pressed = False
        try:
            get_state = self._get_key_state or _get_async_key_state
            while not self._stop.is_set():
                down = bool(get_state(self._virtual_key) & 0x8000)
                now = self._monotonic()
                if down and not pressed:
                    pressed = True
                    self._on_down(self._key, now)
                elif pressed and not down:
                    pressed = False
                    self._on_up(self._key, now)
                self._wake.wait(self._poll_seconds)
                self._wake.clear()
        except Exception:
            self._on_failure("HOTKEY_OBSERVER_FAILED")
        finally:
            if pressed:
                with suppress(Exception):
                    self._on_up(self._key, self._monotonic())


class WindowsShortcutObserver:
    """Observe configured chord rising edges without suppressing or buffering typed keys."""

    def __init__(
        self,
        shortcuts: dict[str, str],
        on_action: Callable[[str], None],
        *,
        poll_seconds: float = 0.02,
        get_key_state: Callable[[int], int] | None = None,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        if not shortcuts or len(shortcuts) > 8 or not 0.005 <= poll_seconds <= 0.1:
            raise ValueError("global shortcut configuration is invalid")
        parsed = {name: _parse_chord(chord) for name, chord in shortcuts.items()}
        if len(set(parsed.values())) != len(parsed):
            raise ValueError("global shortcuts must be unique")
        self._shortcuts = parsed
        self._on_action = on_action
        self._poll_seconds = poll_seconds
        self._get_key_state = get_key_state
        self._on_failure = on_failure or (lambda _code: None)
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._stop.is_set():
                raise HotkeyObserverError("HOTKEY_OBSERVER_CLOSED")
            if self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="gct-shortcuts", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise HotkeyObserverError("HOTKEY_OBSERVER_STOP_FAILED")

    def _run(self) -> None:
        active: set[str] = set()
        try:
            get_state = self._get_key_state or _get_async_key_state
            while not self._stop.is_set():
                states = {
                    virtual_key: bool(get_state(virtual_key) & 0x8000)
                    for virtual_key in {key for chord in self._shortcuts.values() for key in chord}
                }
                for name, chord in self._shortcuts.items():
                    down = all(states[key] for key in chord)
                    if down and name not in active:
                        active.add(name)
                        self._on_action(name)
                    elif not down:
                        active.discard(name)
                self._stop.wait(self._poll_seconds)
        except Exception:
            self._on_failure("HOTKEY_OBSERVER_FAILED")


def _normalize_key(key: str) -> str:
    normalized = key.strip().upper()
    _virtual_key(normalized)
    return normalized


def _virtual_key(key: str) -> int:
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        return ord(key)
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return 0x6F + int(key[1:])
    raise ValueError("hold key must be A-Z, 0-9, or F1-F12")


def _parse_chord(chord: str) -> tuple[int, ...]:
    modifier_keys = {"CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12}
    parts = tuple(part.strip().upper() for part in chord.split("+") if part.strip())
    if not 2 <= len(parts) <= 4 or len(set(parts)) != len(parts):
        raise ValueError("global shortcut must be a unique modifier chord")
    modifiers = parts[:-1]
    if any(part not in modifier_keys for part in modifiers):
        raise ValueError("global shortcut modifiers are invalid")
    main = _virtual_key(parts[-1])
    return tuple(sorted((*[modifier_keys[part] for part in modifiers], main)))


def _get_async_key_state(virtual_key: int) -> int:
    return int(_get_async_key_function()(virtual_key))


@lru_cache(maxsize=1)
def _get_async_key_function() -> Any:
    if not hasattr(ctypes, "WinDLL"):
        raise HotkeyObserverError("HOTKEY_OBSERVER_UNAVAILABLE")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    function = user32.GetAsyncKeyState
    function.argtypes = [ctypes.c_int]
    function.restype = ctypes.c_short
    return function
