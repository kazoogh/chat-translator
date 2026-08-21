from __future__ import annotations

from game_chat_translator.capture.base import CaptureError, CaptureProvider, RawFrame
from game_chat_translator.detection.layout_resolver import ScreenRegion


class FallbackCaptureProvider:
    def __init__(self, primary: CaptureProvider, fallback: CaptureProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._selected: CaptureProvider | None = None
        self._region: ScreenRegion | None = None

    @property
    def active(self) -> bool:
        return self._selected is not None and self._selected.active

    @property
    def using_fallback(self) -> bool:
        return self._selected is self._fallback

    def start(self, region: ScreenRegion) -> None:
        self.close()
        self._region = region
        try:
            self._primary.start(region)
            self._selected = self._primary
        except CaptureError:
            self._fallback.start(region)
            self._selected = self._fallback

    def next_frame(self) -> RawFrame | None:
        if self._selected is None:
            return None
        try:
            return self._selected.next_frame()
        except CaptureError:
            if self._selected is self._fallback or self._region is None:
                raise
            self._primary.close()
            self._selected = None
            region = self._region
            try:
                self._fallback.start(region)
            except CaptureError:
                self._region = None
                raise
            self._selected = self._fallback
            return self._fallback.next_frame()

    def pause(self) -> None:
        if self._selected is not None:
            self._selected.pause()

    def close(self) -> None:
        self._primary.close()
        self._fallback.close()
        self._selected = None
        self._region = None
