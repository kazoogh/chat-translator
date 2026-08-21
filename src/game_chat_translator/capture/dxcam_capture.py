from __future__ import annotations

from typing import Any

from game_chat_translator.capture.base import CaptureError, RawFrame, validate_capture_region
from game_chat_translator.detection.layout_resolver import ScreenRegion


class DxcamCaptureProvider:
    def __init__(self) -> None:
        self._camera: Any = None
        self._region: ScreenRegion | None = None

    @property
    def active(self) -> bool:
        return self._region is not None

    def start(self, region: ScreenRegion) -> None:
        validate_capture_region(region)
        try:
            import dxcam

            if self._camera is None:
                self._camera = dxcam.create(output_color="BGRA")
        except (ImportError, OSError, RuntimeError) as exc:
            raise CaptureError("DXGI capture is unavailable") from exc
        self._region = region

    def next_frame(self) -> RawFrame | None:
        if self._camera is None or self._region is None:
            return None
        region = self._region
        try:
            image = self._camera.grab(region=(region.left, region.top, region.right, region.bottom))
        except (OSError, RuntimeError) as exc:
            raise CaptureError("DXGI region capture failed") from exc
        if image is None:
            return None
        return RawFrame(region.width, region.height, "BGRA", image.tobytes())

    def pause(self) -> None:
        self._region = None

    def close(self) -> None:
        camera = self._camera
        self._region = None
        self._camera = None
        if camera is not None and hasattr(camera, "stop"):
            camera.stop()
