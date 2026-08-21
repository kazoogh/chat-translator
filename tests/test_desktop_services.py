from __future__ import annotations

from pathlib import Path

import pytest

from game_chat_translator.application import ApplicationController
from game_chat_translator.core_runtime import CoreRuntime
from game_chat_translator.desktop import (
    _build_monitoring,
    _calibration_restore_target,
    _persist_calibration_after_generation_handoff,
)
from game_chat_translator.lifecycle import LifecycleState
from game_chat_translator.models import ChatRegion
from game_chat_translator.settings import AppSettings
from game_chat_translator.translation.base import CancellationToken, TranslationRequest
from game_chat_translator.ui.event_queue import UiEventQueue


@pytest.mark.parametrize(
    ("previous", "saved", "expected"),
    [
        (LifecycleState.PAUSED, True, LifecycleState.PAUSED),
        (LifecycleState.MONITORING, True, LifecycleState.MONITORING),
        (LifecycleState.NEEDS_SETUP, True, LifecycleState.MONITORING),
        (LifecycleState.DEGRADED, True, LifecycleState.DEGRADED),
        (LifecycleState.PAUSED, False, LifecycleState.PAUSED),
        (LifecycleState.MONITORING, False, LifecycleState.MONITORING),
        (LifecycleState.NEEDS_SETUP, False, LifecycleState.NEEDS_SETUP),
        (LifecycleState.DEGRADED, False, LifecycleState.DEGRADED),
    ],
)
def test_calibration_restores_only_the_intended_operational_state(
    previous: LifecycleState, saved: bool, expected: LifecycleState
) -> None:
    assert _calibration_restore_target(previous, saved=saved) is expected


class _TranslationProvider:
    provider_id = "desktop-composition-fixture"
    model_id = "desktop-composition-fixture"

    def health_check(self) -> bool:
        return True

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        del timeout_seconds, cancellation
        return request.source_text

    def close(self) -> None:
        pass


class _ReadyOcrSetup:
    def __init__(self, root: Path) -> None:
        self._detection = root / "det"
        self._recognition = root / "rec"
        self._detection.mkdir(parents=True)
        self._recognition.mkdir(parents=True)

    def ready_paths(self) -> tuple[Path, Path]:
        return self._detection, self._recognition


def test_production_monitoring_composition_is_constructible_with_local_models(
    tmp_path: Path,
) -> None:
    runtime = CoreRuntime(
        state_path=tmp_path / "state.sqlite3",
        model_root=tmp_path / "models",
        lightweight_factory=_TranslationProvider,
    )
    controller = ApplicationController(AppSettings(), UiEventQueue())

    monitoring = _build_monitoring(
        runtime,
        controller,
        AppSettings(),
        _ReadyOcrSetup(tmp_path / "ocr"),  # type: ignore[arg-type]
    )

    assert monitoring is not None
    assert runtime.active_pipeline_count == 1
    monitoring.close()
    assert runtime.active_pipeline_count == 0

    rebuilt = _build_monitoring(
        runtime,
        controller,
        AppSettings(),
        _ReadyOcrSetup(tmp_path / "ocr-rebuilt"),  # type: ignore[arg-type]
    )
    assert rebuilt is not None
    assert runtime.active_pipeline_count == 1
    rebuilt.close()
    assert runtime.active_pipeline_count == 0
    runtime.close()


class _GenerationRuntime:
    def __init__(self, calls: list[str], *, fails: bool = False) -> None:
        self.calls = calls
        self.fails = fails

    def advance_layout_generation(self) -> int:
        self.calls.append("runtime-generation")
        if self.fails:
            raise RuntimeError("fixture")
        return 9


class _GenerationMonitoring:
    def __init__(self, calls: list[str], *, fails: bool = False) -> None:
        self.calls = calls
        self.fails = fails

    def advance_layout_generation(self, generation: int) -> None:
        assert generation == 9
        self.calls.append("monitoring-generation")
        if self.fails:
            raise RuntimeError("fixture")


class _CalibrationRepository:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def save_calibration(self, *_args: object) -> None:
        self.calls.append("persist")


def _chat_region() -> ChatRegion:
    return ChatRegion(
        x=0.1,
        y=0.2,
        width=0.4,
        height=0.3,
        layout_id="default",
        reference_client_width=1000,
        reference_client_height=500,
        reference_dpi=96,
    )


@pytest.mark.parametrize(("runtime_fails", "monitoring_fails"), [(True, False), (False, True)])
def test_calibration_is_not_persisted_before_generation_handoff(
    runtime_fails: bool, monitoring_fails: bool
) -> None:
    calls: list[str] = []
    with pytest.raises(RuntimeError):
        _persist_calibration_after_generation_handoff(
            _GenerationRuntime(calls, fails=runtime_fails),  # type: ignore[arg-type]
            _GenerationMonitoring(calls, fails=monitoring_fails),  # type: ignore[arg-type]
            _CalibrationRepository(calls),
            "stalzone.default",
            "DISPLAY1",
            _chat_region(),
        )
    assert "persist" not in calls


def test_calibration_persists_only_after_both_generation_owners() -> None:
    calls: list[str] = []
    _persist_calibration_after_generation_handoff(
        _GenerationRuntime(calls),  # type: ignore[arg-type]
        _GenerationMonitoring(calls),  # type: ignore[arg-type]
        _CalibrationRepository(calls),
        "stalzone.default",
        "DISPLAY1",
        _chat_region(),
    )
    assert calls == ["runtime-generation", "monitoring-generation", "persist"]
