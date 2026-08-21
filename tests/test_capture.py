from __future__ import annotations

from dataclasses import dataclass

import pytest

from game_chat_translator.capture.base import CaptureError, RawFrame
from game_chat_translator.capture.router import FallbackCaptureProvider
from game_chat_translator.capture.service import RegionCaptureService
from game_chat_translator.detection.layout_resolver import ScreenRegion
from game_chat_translator.models import Bounds, ChatRegion, WindowIdentity


@dataclass
class FakeCapture:
    fail_start: bool = False
    fail_next: bool = False
    active: bool = False
    started_region: ScreenRegion | None = None
    close_count: int = 0

    def start(self, region: ScreenRegion) -> None:
        if self.fail_start:
            raise CaptureError("synthetic failure")
        self.active = True
        self.started_region = region

    def next_frame(self) -> RawFrame | None:
        if self.fail_next:
            raise CaptureError("synthetic failure")
        if not self.active or self.started_region is None:
            return None
        region = self.started_region
        return RawFrame(
            region.width, region.height, "BGRA", bytes(region.width * region.height * 4)
        )

    def pause(self) -> None:
        self.active = False

    def close(self) -> None:
        self.active = False
        self.close_count += 1


def test_service_passes_only_derived_calibrated_region() -> None:
    backend = FakeCapture()
    service = RegionCaptureService(backend)
    region = ChatRegion(
        x=0.25,
        y=0.5,
        width=0.5,
        height=0.25,
        layout_id="default",
        reference_client_width=800,
        reference_client_height=600,
        reference_dpi=96,
    )
    window = WindowIdentity(
        process_id=1,
        executable="game.exe",
        title="Game",
        window_class="Game",
        client_bounds=Bounds(left=100, top=200, width=800, height=600),
        monitor_id="primary",
        dpi=96,
    )
    assert service.configure(region, window) is True
    assert backend.started_region == ScreenRegion(left=300, top=500, width=400, height=150)
    assert service.next_frame() is not None


def test_service_pauses_on_minimize_or_missing_calibration() -> None:
    backend = FakeCapture(active=True)
    service = RegionCaptureService(backend)
    assert service.configure(None, None) is False
    assert backend.active is False


@pytest.mark.parametrize("fail_on", ["start", "next"])
def test_dxcam_failure_degrades_to_mss_once(fail_on: str) -> None:
    primary = FakeCapture(fail_start=fail_on == "start", fail_next=fail_on == "next")
    fallback = FakeCapture()
    router = FallbackCaptureProvider(primary, fallback)
    region = ScreenRegion(10, 20, 50, 30)
    router.start(region)
    frame = router.next_frame()
    assert frame is not None
    assert router.using_fallback is True
    assert fallback.started_region == region


def test_runtime_failover_failure_leaves_router_stopped() -> None:
    primary = FakeCapture(fail_next=True)
    fallback = FakeCapture(fail_start=True)
    router = FallbackCaptureProvider(primary, fallback)
    router.start(ScreenRegion(0, 0, 10, 10))
    with pytest.raises(CaptureError):
        router.next_frame()
    assert router.active is False
    assert router.next_frame() is None
