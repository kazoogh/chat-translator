from __future__ import annotations

from game_chat_translator.capture.base import CaptureProvider, RawFrame
from game_chat_translator.detection.layout_resolver import LayoutResolver
from game_chat_translator.models import ChatRegion, WindowIdentity


class RegionCaptureService:
    """Guarantee providers only receive a derived calibrated region."""

    def __init__(self, provider: CaptureProvider, resolver: LayoutResolver | None = None) -> None:
        self._provider = provider
        self._resolver = resolver or LayoutResolver()

    def configure(self, calibration: ChatRegion | None, window: WindowIdentity | None) -> bool:
        region = self._resolver.resolve(calibration, window)
        if region is None:
            self._provider.pause()
            return False
        self._provider.start(region)
        return True

    def next_frame(self) -> RawFrame | None:
        return self._provider.next_frame()

    def pause(self) -> None:
        self._provider.pause()

    def close(self) -> None:
        self._provider.close()
