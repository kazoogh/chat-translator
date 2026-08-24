from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import Protocol

from game_chat_translator.application_pipeline import ApplicationPipelineCoordinator
from game_chat_translator.capture.base import CaptureError
from game_chat_translator.capture.service import RegionCaptureService
from game_chat_translator.detection.game_detector import ProfileResolver
from game_chat_translator.models import CapturedFrame, ChatRegion, WindowIdentity
from game_chat_translator.profiles.schema import GameProfile
from game_chat_translator.translation.pipeline import TranslationPipeline
from game_chat_translator.vision.preprocess import PreprocessConfig


class ForegroundWindowProvider(Protocol):
    def get_active_window(self) -> WindowIdentity | None: ...


class CalibrationLookup(Protocol):
    def find_calibration(
        self,
        profile_id: str,
        layout_id: str,
        monitor_id: str,
        client_width: int,
        client_height: int,
        dpi: int,
        game_ui_scale: float | None,
    ) -> ChatRegion | None: ...


class LiveFrameSource:
    """Foreground/profile/calibration boundary that captures only a resolved chat region."""

    def __init__(
        self,
        foreground: ForegroundWindowProvider,
        profiles: Mapping[str, GameProfile],
        state: CalibrationLookup,
        capture: RegionCaptureService,
        *,
        active_profile: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if active_profile not in profiles:
            raise ValueError("active profile is unavailable")
        self._foreground = foreground
        self._resolver = ProfileResolver(profiles, clock=monotonic)
        self._state = state
        self._capture = capture
        self._active_profile = active_profile
        self._monotonic = monotonic
        self._configured_key: tuple[object, ...] | None = None
        self._region: ChatRegion | None = None

    def next_frame(self) -> CapturedFrame | None:
        window = self._foreground.get_active_window()
        resolution = self._resolver.resolve(window)
        if (
            window is None
            or resolution.should_pause
            or resolution.profile_id != self._active_profile
        ):
            self.pause()
            return None
        region = self._state.find_calibration(
            self._active_profile,
            "default",
            window.monitor_id,
            window.client_bounds.width,
            window.client_bounds.height,
            window.dpi,
            None,
        )
        key = (
            window,
            region,
        )
        if region is None:
            self.pause()
            return None
        if key != self._configured_key:
            if not self._capture.configure(region, window):
                self.pause()
                return None
            self._configured_key = key
            self._region = region
        raw = self._capture.next_frame()
        if raw is None:
            return None
        now = self._monotonic()
        return CapturedFrame(
            captured_at=datetime.now(UTC),
            monotonic_seconds=max(0.0, now),
            profile_id=self._active_profile,
            layout_id=region.layout_id,
            region=region,
            pixel_format=raw.pixel_format,
            width=raw.width,
            height=raw.height,
            pixels=raw.pixels,
        )

    def pause(self) -> None:
        self._capture.pause()
        self._configured_key = None
        self._region = None

    def close(self) -> None:
        self._capture.close()
        self._configured_key = None
        self._region = None


class MonitoringWorker:
    """Single compute owner; capture remains independent from nonblocking speech admission."""

    def __init__(
        self,
        source: LiveFrameSource,
        coordinator: ApplicationPipelineCoordinator,
        preprocess: PreprocessConfig,
        *,
        generation: int = 1,
        interval_seconds: float = 0.25,
        on_failure: Callable[[str], None] = lambda _code: None,
    ) -> None:
        if generation < 0 or interval_seconds <= 0:
            raise ValueError("monitoring generation and interval are invalid")
        self._source = source
        self._coordinator = coordinator
        self._preprocess = preprocess
        self._generation = generation
        self._interval = interval_seconds
        self._on_failure = on_failure
        self._stop = Event()
        self._wake = Event()
        self._paused_ack = Event()
        self._paused_ack.set()
        self._paused = True
        self._pause_requested = False
        self._lock = Lock()
        self._source_lock = Lock()
        self._pending_layout: tuple[int, Event, list[bool]] | None = None
        self._thread = Thread(target=self._run, name="gct-monitoring", daemon=True)
        self._started = False

    @property
    def translation_pipeline(self) -> TranslationPipeline:
        return self._coordinator.translation_pipeline

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread.start()

    def resume(self) -> None:
        self.start()
        with self._lock:
            self._paused = False
            self._pause_requested = False
            self._paused_ack.clear()
        self._wake.set()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            if not self._started:
                self._pause_requested = False
                self._paused_ack.set()
                return
            self._pause_requested = True
            self._paused_ack.clear()
        self._wake.set()

    def wait_paused(self, timeout: float = 5.0) -> bool:
        return self._paused_ack.wait(timeout)

    def advance_layout_generation(self, layout_generation: int, timeout: float = 5.0) -> None:
        if layout_generation < 0:
            raise ValueError("layout generation is invalid")
        completed = Event()
        result: list[bool] = []
        self.start()
        with self._lock:
            if self._pending_layout is not None:
                raise RuntimeError("a layout update is already pending")
            self._pending_layout = (layout_generation, completed, result)
        self._wake.set()
        if not completed.wait(timeout):
            raise RuntimeError("monitoring did not apply the layout generation")
        if result != [True]:
            raise RuntimeError("monitoring rejected the layout generation")

    def close(self, timeout: float = 8.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._started:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise RuntimeError("monitoring worker did not stop")
        with self._source_lock:
            self._source.close()
        self._coordinator.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                paused = self._paused
                pause_requested = self._pause_requested
                self._pause_requested = False
                pending_layout = self._pending_layout
                self._pending_layout = None
                if pending_layout is not None:
                    self._generation += 1
                frame_generation = self._generation
            if pause_requested:
                try:
                    with self._source_lock:
                        self._source.pause()
                except (CaptureError, OSError, RuntimeError, TypeError, ValueError):
                    self._on_failure("MONITORING_PAUSE_FAILED")
                finally:
                    self._paused_ack.set()
            if pending_layout is not None:
                layout_generation, completed, result = pending_layout
                try:
                    self._coordinator.advance_frame_layout(
                        frame=frame_generation,
                        layout=layout_generation,
                    )
                    result.append(True)
                except (RuntimeError, TypeError, ValueError):
                    self._on_failure("MONITORING_GENERATION_FAILED")
                    result.append(False)
                finally:
                    completed.set()
            if paused:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            try:
                with self._source_lock:
                    frame = self._source.next_frame()
                if frame is not None:
                    self._coordinator.submit_frame(
                        frame, self._preprocess, generation=self._generation
                    )
                while self._coordinator.process_once():
                    if self._stop.is_set():
                        break
            except (CaptureError, OSError, RuntimeError, TypeError, ValueError):
                self._on_failure("MONITORING_DEGRADED")
                with self._source_lock:
                    self._source.pause()
                self._paused_ack.set()
            self._wake.wait(self._interval)
            self._wake.clear()
