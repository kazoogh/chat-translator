from __future__ import annotations

import pytest

from game_chat_translator.lifecycle import Lifecycle, LifecycleState


def test_lifecycle_rejects_invalid_transition() -> None:
    lifecycle = Lifecycle()
    lifecycle.transition(LifecycleState.PAUSED)
    lifecycle.transition(LifecycleState.MONITORING)
    lifecycle.transition(LifecycleState.STOPPING)
    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        lifecycle.transition(LifecycleState.MONITORING)
