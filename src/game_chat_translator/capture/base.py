from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from game_chat_translator.detection.layout_resolver import ScreenRegion


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RawFrame:
    width: int
    height: int
    pixel_format: str
    pixels: bytes


class CaptureProvider(Protocol):
    @property
    def active(self) -> bool: ...

    def start(self, region: ScreenRegion) -> None: ...

    def next_frame(self) -> RawFrame | None: ...

    def pause(self) -> None: ...

    def close(self) -> None: ...


def validate_capture_region(region: ScreenRegion) -> None:
    if region.width <= 0 or region.height <= 0:
        raise CaptureError("capture region must be non-empty")
    if region.width > 16_384 or region.height > 16_384:
        raise CaptureError("capture region exceeds safe dimensions")
