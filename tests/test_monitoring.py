from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Event, current_thread

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.capture.service import RegionCaptureService
from game_chat_translator.detection.layout_resolver import ScreenRegion
from game_chat_translator.models import Bounds, ChatRegion, WindowIdentity
from game_chat_translator.monitoring import LiveFrameSource, MonitoringWorker
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.resource_paths import bundled_resource_root
from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.vision.preprocess import PreprocessConfig


@dataclass
class _Clock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


@dataclass
class _Foreground:
    window: WindowIdentity | None

    def get_active_window(self) -> WindowIdentity | None:
        return self.window


@dataclass
class _State:
    region: ChatRegion | None

    def find_calibration(self, *_args: object) -> ChatRegion | None:
        return self.region


@dataclass
class _CaptureProvider:
    frames: list[RawFrame]
    started: list[ScreenRegion] = field(default_factory=list)
    pauses: int = 0
    closes: int = 0

    @property
    def active(self) -> bool:
        return bool(self.started) and self.closes == 0

    def start(self, region: ScreenRegion) -> None:
        self.started.append(region)

    def next_frame(self) -> RawFrame | None:
        return self.frames.pop(0) if self.frames else None

    def pause(self) -> None:
        self.pauses += 1

    def close(self) -> None:
        self.closes += 1


def _window(*, title: str = "STALZONE", minimized: bool = False) -> WindowIdentity:
    return WindowIdentity(
        process_id=41,
        executable="javaw.exe",
        title=title,
        window_class="LWJGL",
        client_bounds=Bounds(left=-1200, top=40, width=1000, height=500),
        monitor_id="DISPLAY2",
        dpi=120,
        minimized=minimized,
    )


def _region() -> ChatRegion:
    return ChatRegion(
        x=0.1,
        y=0.4,
        width=0.5,
        height=0.4,
        layout_id="default",
        reference_client_width=1000,
        reference_client_height=500,
        reference_dpi=120,
    )


def test_live_source_debounces_then_captures_only_calibrated_region() -> None:
    clock = _Clock()
    foreground = _Foreground(_window())
    provider = _CaptureProvider([RawFrame(2, 1, "BGRA", b"\x00" * 8)])
    profiles = ResourceRegistry(bundled_resource_root()).load_all()
    source = LiveFrameSource(
        foreground,
        {key: value.profile for key, value in profiles.items()},
        _State(_region()),
        RegionCaptureService(provider),
        active_profile="stalzone.default",
        monotonic=clock,
    )

    assert source.next_frame() is None
    assert provider.started == []
    clock.value = 1.3
    frame = source.next_frame()

    assert frame is not None
    assert frame.region == _region()
    assert provider.started == [ScreenRegion(left=-1100, top=240, width=500, height=200)]

    foreground.window = _window(title="Private unrelated window")
    assert source.next_frame() is None
    assert provider.pauses >= 2


@dataclass
class _WorkerSource:
    frame: object | None = None
    calls: int = 0
    pauses: int = 0
    closes: int = 0

    def next_frame(self) -> object | None:
        self.calls += 1
        return self.frame

    def pause(self) -> None:
        self.pauses += 1

    def close(self) -> None:
        self.closes += 1


@dataclass
class _Coordinator:
    submissions: int = 0
    generations: list[tuple[int, int]] = field(default_factory=list)
    closes: int = 0

    def submit_frame(self, *_args: object, **_kwargs: object) -> OfferResult:
        self.submissions += 1
        return OfferResult.ACCEPTED

    def process_once(self) -> bool:
        return False

    def advance_frame_layout(self, *, frame: int, layout: int) -> None:
        self.generations.append((frame, layout))

    def close(self) -> None:
        self.closes += 1


def test_monitoring_worker_pause_generation_and_close_are_owned() -> None:
    source = _WorkerSource()
    coordinator = _Coordinator()
    worker = MonitoringWorker(  # type: ignore[arg-type]
        source,
        coordinator,  # type: ignore[arg-type]
        PreprocessConfig(),
        interval_seconds=0.01,
    )

    worker.resume()
    deadline = time.monotonic() + 1
    while source.calls == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert source.calls > 0

    worker.pause()
    assert worker.wait_paused()
    worker.advance_layout_generation(7)
    assert coordinator.generations == [(2, 7)]
    calls_after_pause = source.calls
    time.sleep(0.04)
    assert source.calls == calls_after_pause

    worker.close()
    assert source.closes == 1
    assert coordinator.closes == 1


def test_unstarted_monitoring_is_already_safely_paused_for_first_calibration() -> None:
    source = _WorkerSource()
    coordinator = _Coordinator()
    worker = MonitoringWorker(  # type: ignore[arg-type]
        source,
        coordinator,  # type: ignore[arg-type]
        PreprocessConfig(),
    )

    worker.pause()

    assert worker.wait_paused(0)
    assert source.pauses == 0
    assert source.calls == 0
    worker.close()


@dataclass
class _BlockingSource:
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    paused_on: str | None = None

    def next_frame(self) -> None:
        self.entered.set()
        self.release.wait(2)

    def pause(self) -> None:
        self.paused_on = current_thread().name

    def close(self) -> None:
        pass


def test_pause_returns_without_waiting_for_blocked_capture_and_owner_applies_it() -> None:
    source = _BlockingSource()
    coordinator = _Coordinator()
    worker = MonitoringWorker(  # type: ignore[arg-type]
        source,
        coordinator,  # type: ignore[arg-type]
        PreprocessConfig(),
        interval_seconds=0.01,
    )
    worker.resume()
    assert source.entered.wait(1)

    started = time.monotonic()
    worker.pause()
    assert time.monotonic() - started < 0.1
    assert source.paused_on is None

    source.release.set()
    assert worker.wait_paused(1)
    assert source.paused_on == "gct-monitoring"
    worker.close()
