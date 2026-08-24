from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class HoldAction(StrEnum):
    NONE = "none"
    START_RECORDING = "start_recording"
    FINISH_RECORDING = "finish_recording"
    CANCEL_RECORDING = "cancel_recording"


@dataclass(frozen=True, slots=True)
class HoldTransition:
    action: HoldAction
    held_seconds: float = 0.0
    reason: str | None = None


class HoldKeyStateMachine:
    """Pure non-suppressing key-edge policy using injected monotonic timestamps."""

    def __init__(self, key: str, *, minimum_hold_ms: int = 180) -> None:
        normalized = _normalize_key(key)
        if not normalized or not 100 <= minimum_hold_ms <= 5_000:
            raise ValueError("hold-key configuration is invalid")
        self._key = normalized
        self._minimum = minimum_hold_ms / 1_000
        self._pressed_at: float | None = None
        self._closed = False

    @property
    def recording(self) -> bool:
        return self._pressed_at is not None

    def key_down(self, key: str, *, now: float) -> HoldTransition:
        _validate_time(now)
        if self._closed or _normalize_key(key) != self._key or self._pressed_at is not None:
            return HoldTransition(HoldAction.NONE)
        self._pressed_at = now
        return HoldTransition(HoldAction.START_RECORDING)

    def key_up(self, key: str, *, now: float) -> HoldTransition:
        _validate_time(now)
        if self._closed or _normalize_key(key) != self._key or self._pressed_at is None:
            return HoldTransition(HoldAction.NONE)
        started, self._pressed_at = self._pressed_at, None
        held = max(0.0, now - started)
        if held < self._minimum:
            return HoldTransition(HoldAction.CANCEL_RECORDING, held, "accidental_tap")
        return HoldTransition(HoldAction.FINISH_RECORDING, held)

    def cancel(self, *, reason: str = "cancelled") -> HoldTransition:
        if self._pressed_at is None:
            return HoldTransition(HoldAction.NONE)
        self._pressed_at = None
        return HoldTransition(HoldAction.CANCEL_RECORDING, reason=reason)

    def shutdown(self) -> HoldTransition:
        transition = self.cancel(reason="shutdown")
        self._closed = True
        return transition


def _normalize_key(key: str) -> str:
    return key.strip().casefold()


def _validate_time(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError("hold-key monotonic timestamp is invalid")
