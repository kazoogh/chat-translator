from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from game_chat_translator.models import ChatRegion


class CalibrationError(RuntimeError):
    pass


class ResizeHandle(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


@dataclass(frozen=True, slots=True)
class PixelRect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class CalibrationMetadata:
    profile_id: str
    layout_id: str
    monitor_id: str
    client_width: int
    client_height: int
    dpi: int


@dataclass(frozen=True, slots=True)
class CalibrationViewport:
    image_width: int
    image_height: int
    scale: float

    @property
    def view_width(self) -> int:
        return max(1, round(self.image_width * self.scale))

    @property
    def view_height(self) -> int:
        return max(1, round(self.image_height * self.scale))

    @classmethod
    def fit(
        cls,
        image_width: int,
        image_height: int,
        available_width: int,
        available_height: int,
        *,
        side_panel_width: int,
        device_pixel_ratio: float,
    ) -> CalibrationViewport:
        if min(image_width, image_height, available_width, available_height) <= 0:
            raise CalibrationError("calibration viewport dimensions must be positive")
        usable_width = max(1, available_width - side_panel_width)
        scale = min(
            usable_width / image_width,
            available_height / image_height,
            1.0 / max(device_pixel_ratio, 1.0),
        )
        return cls(image_width, image_height, scale)

    def view_to_image(self, x: int, y: int) -> tuple[int, int]:
        return (
            min(max(round(x / self.scale), 0), self.image_width),
            min(max(round(y / self.scale), 0), self.image_height),
        )

    def image_rect_to_view(self, rectangle: PixelRect) -> PixelRect:
        return PixelRect(
            round(rectangle.left * self.scale),
            round(rectangle.top * self.scale),
            max(1, round(rectangle.width * self.scale)),
            max(1, round(rectangle.height * self.scale)),
        )


class CalibrationSession:
    """Pure state model for a frozen, memory-only calibration screenshot."""

    def __init__(
        self,
        metadata: CalibrationMetadata,
        frozen_bgra: bytes,
        *,
        persist: Callable[[ChatRegion], object],
    ) -> None:
        expected_bytes = metadata.client_width * metadata.client_height * 4
        if len(frozen_bgra) != expected_bytes:
            raise CalibrationError("frozen screenshot dimensions do not match its pixel buffer")
        self.metadata = metadata
        self._frozen_bgra = frozen_bgra
        self._persist = persist
        self._selection: PixelRect | None = None
        self._drag_origin: tuple[int, int] | None = None
        self._cancelled = False
        self._saved = False
        self.preview_has_likely_text: bool | None = None
        self.preview_lines: tuple[str, ...] = ()

    @property
    def selection(self) -> PixelRect | None:
        return self._selection

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def saved(self) -> bool:
        return self._saved

    @property
    def frozen_bgra(self) -> bytes:
        self._ensure_open()
        return self._frozen_bgra

    def begin_drag(self, x: int, y: int) -> None:
        self._ensure_open()
        self._drag_origin = self._clamp_point(x, y)
        self._selection = None

    def update_drag(self, x: int, y: int) -> PixelRect:
        self._ensure_open()
        if self._drag_origin is None:
            raise CalibrationError("drag has not started")
        current = self._clamp_point(x, y)
        left = min(self._drag_origin[0], current[0])
        top = min(self._drag_origin[1], current[1])
        right = max(self._drag_origin[0], current[0])
        bottom = max(self._drag_origin[1], current[1])
        self._selection = PixelRect(left, top, right - left, bottom - top)
        return self._selection

    def end_drag(self, x: int, y: int) -> PixelRect:
        selection = self.update_drag(x, y)
        self._drag_origin = None
        if selection.width == 0 or selection.height == 0:
            self._selection = None
            raise CalibrationError("chat selection must be non-empty")
        return selection

    def move(self, dx: int, dy: int) -> PixelRect:
        selection = self._require_selection()
        left = min(max(selection.left + dx, 0), self.metadata.client_width - selection.width)
        top = min(max(selection.top + dy, 0), self.metadata.client_height - selection.height)
        self._selection = PixelRect(left, top, selection.width, selection.height)
        return self._selection

    def resize(self, handle: ResizeHandle, dx: int, dy: int) -> PixelRect:
        selection = self._require_selection()
        left, top, right, bottom = (
            selection.left,
            selection.top,
            selection.right,
            selection.bottom,
        )
        if handle in {ResizeHandle.TOP_LEFT, ResizeHandle.BOTTOM_LEFT}:
            left = min(max(left + dx, 0), right - 1)
        else:
            right = max(min(right + dx, self.metadata.client_width), left + 1)
        if handle in {ResizeHandle.TOP_LEFT, ResizeHandle.TOP_RIGHT}:
            top = min(max(top + dy, 0), bottom - 1)
        else:
            bottom = max(min(bottom + dy, self.metadata.client_height), top + 1)
        self._selection = PixelRect(left, top, right - left, bottom - top)
        return self._selection

    def nudge(self, dx: int, dy: int, *, resize: bool = False) -> PixelRect:
        if resize:
            return self.resize(ResizeHandle.BOTTOM_RIGHT, dx, dy)
        return self.move(dx, dy)

    def reset(self) -> None:
        self._ensure_open()
        self._selection = None
        self._drag_origin = None
        self.preview_has_likely_text = None
        self.preview_lines = ()

    def retry(self, frozen_bgra: bytes) -> None:
        self._ensure_open()
        expected_bytes = self.metadata.client_width * self.metadata.client_height * 4
        if len(frozen_bgra) != expected_bytes:
            raise CalibrationError(
                "replacement screenshot dimensions do not match its pixel buffer"
            )
        self._frozen_bgra = frozen_bgra
        self.reset()

    def set_preview_result(
        self, *, has_likely_text: bool | None, lines: tuple[str, ...] = ()
    ) -> None:
        self._ensure_open()
        self.preview_has_likely_text = has_likely_text
        self.preview_lines = tuple(line[:160] for line in lines[:8])

    def cancel(self) -> None:
        self._ensure_open()
        self._selection = None
        self._frozen_bgra = b""
        self._cancelled = True

    def preview_bgra(self) -> bytes:
        selection = self._require_selection()
        stride = self.metadata.client_width * 4
        output = bytearray()
        for y in range(selection.top, selection.bottom):
            start = y * stride + selection.left * 4
            output.extend(self._frozen_bgra[start : start + selection.width * 4])
        return bytes(output)

    def save(self, *, confirm_no_text: bool = False) -> ChatRegion:
        selection = self._require_selection()
        if self.preview_has_likely_text is False and not confirm_no_text:
            raise CalibrationError(
                "no likely chat text was detected; explicit confirmation is required to save"
            )
        region = ChatRegion(
            x=selection.left / self.metadata.client_width,
            y=selection.top / self.metadata.client_height,
            width=selection.width / self.metadata.client_width,
            height=selection.height / self.metadata.client_height,
            layout_id=self.metadata.layout_id,
            reference_client_width=self.metadata.client_width,
            reference_client_height=self.metadata.client_height,
            reference_dpi=self.metadata.dpi,
        )
        self._persist(region)
        self._frozen_bgra = b""
        self._saved = True
        return region

    def _ensure_open(self) -> None:
        if self._cancelled or self._saved:
            raise CalibrationError("calibration session is closed")

    def _require_selection(self) -> PixelRect:
        self._ensure_open()
        if self._selection is None:
            raise CalibrationError("chat selection is empty")
        return self._selection

    def _clamp_point(self, x: int, y: int) -> tuple[int, int]:
        return (
            min(max(x, 0), self.metadata.client_width),
            min(max(y, 0), self.metadata.client_height),
        )
