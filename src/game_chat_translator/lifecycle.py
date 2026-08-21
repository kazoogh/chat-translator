from __future__ import annotations

from enum import StrEnum


class LifecycleState(StrEnum):
    STARTING = "starting"
    NEEDS_SETUP = "needs_setup"
    PAUSED = "paused"
    MONITORING = "monitoring"
    RECORDING_REPLY = "recording_reply"
    PROCESSING_REPLY = "processing_reply"
    DEGRADED = "degraded"
    STOPPING = "stopping"


_ALLOWED: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.STARTING: frozenset(
        {
            LifecycleState.NEEDS_SETUP,
            LifecycleState.PAUSED,
            LifecycleState.DEGRADED,
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.NEEDS_SETUP: frozenset(
        {
            LifecycleState.PAUSED,
            LifecycleState.MONITORING,
            LifecycleState.DEGRADED,
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.PAUSED: frozenset(
        {
            LifecycleState.MONITORING,
            LifecycleState.NEEDS_SETUP,
            LifecycleState.DEGRADED,
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.MONITORING: frozenset(
        {
            LifecycleState.PAUSED,
            LifecycleState.RECORDING_REPLY,
            LifecycleState.DEGRADED,
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.RECORDING_REPLY: frozenset(
        {LifecycleState.PROCESSING_REPLY, LifecycleState.MONITORING, LifecycleState.STOPPING}
    ),
    LifecycleState.PROCESSING_REPLY: frozenset(
        {LifecycleState.MONITORING, LifecycleState.DEGRADED, LifecycleState.STOPPING}
    ),
    LifecycleState.DEGRADED: frozenset(
        {
            LifecycleState.PAUSED,
            LifecycleState.MONITORING,
            LifecycleState.NEEDS_SETUP,
            LifecycleState.STOPPING,
        }
    ),
    LifecycleState.STOPPING: frozenset(),
}


class Lifecycle:
    def __init__(self) -> None:
        self._state = LifecycleState.STARTING

    @property
    def state(self) -> LifecycleState:
        return self._state

    def transition(self, target: LifecycleState) -> None:
        if target not in _ALLOWED[self._state]:
            raise ValueError(f"invalid lifecycle transition: {self._state} -> {target}")
        self._state = target
