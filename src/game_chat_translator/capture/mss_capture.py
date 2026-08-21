from __future__ import annotations

from typing import Any

from game_chat_translator.capture.base import CaptureError, RawFrame, validate_capture_region
from game_chat_translator.detection.layout_resolver import ScreenRegion


class MssCaptureProvider:
    def __init__(self) -> None:
        self._session: Any = None
        self._region: ScreenRegion | None = None

    @property
    def active(self) -> bool:
        return self._region is not None

    def start(self, region: ScreenRegion) -> None:
        validate_capture_region(region)
        try:
            import mss

            if self._session is None:
                self._session = mss.mss()
        except (ImportError, OSError, RuntimeError) as exc:
            raise CaptureError("MSS capture is unavailable") from exc
        self._region = region

    def next_frame(self) -> RawFrame | None:
        if self._session is None or self._region is None:
            return None
        region = self._region
        try:
            image = self._session.grab(
                {
                    "left": region.left,
                    "top": region.top,
                    "width": region.width,
                    "height": region.height,
                }
            )
        except (OSError, RuntimeError) as exc:
            raise CaptureError("MSS region capture failed") from exc
        return RawFrame(region.width, region.height, "BGRA", bytes(image.bgra))

    def pause(self) -> None:
        self._region = None

    def close(self) -> None:
        session = self._session
        self._region = None
        self._session = None
        if session is not None:
            session.close()
