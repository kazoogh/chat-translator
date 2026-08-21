from __future__ import annotations

from dataclasses import dataclass

from game_chat_translator.models import Bounds, ChatRegion, WindowIdentity


@dataclass(frozen=True, slots=True)
class ScreenRegion:
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


def normalized_to_screen(region: ChatRegion, client_bounds: Bounds) -> ScreenRegion:
    left_offset = round(region.x * client_bounds.width)
    top_offset = round(region.y * client_bounds.height)
    right_offset = round((region.x + region.width) * client_bounds.width)
    bottom_offset = round((region.y + region.height) * client_bounds.height)
    left_offset = min(max(left_offset, 0), client_bounds.width - 1)
    top_offset = min(max(top_offset, 0), client_bounds.height - 1)
    right_offset = min(max(right_offset, left_offset + 1), client_bounds.width)
    bottom_offset = min(max(bottom_offset, top_offset + 1), client_bounds.height)
    return ScreenRegion(
        left=client_bounds.left + left_offset,
        top=client_bounds.top + top_offset,
        width=right_offset - left_offset,
        height=bottom_offset - top_offset,
    )


class LayoutResolver:
    @staticmethod
    def compatibility_score(region: ChatRegion, window: WindowIdentity) -> float:
        reference_aspect = region.reference_client_width / region.reference_client_height
        current_aspect = window.client_bounds.width / window.client_bounds.height
        aspect_delta = abs(current_aspect - reference_aspect) / reference_aspect
        width_ratio = window.client_bounds.width / region.reference_client_width
        height_ratio = window.client_bounds.height / region.reference_client_height
        dpi_ratio = window.dpi / region.reference_dpi
        if aspect_delta > 0.20:
            return 0.0
        if not (0.5 <= width_ratio <= 2.0 and 0.5 <= height_ratio <= 2.0):
            return 0.0
        if not 0.75 <= dpi_ratio <= 1.5:
            return 0.0
        return max(0.0, 1.0 - aspect_delta - abs(1.0 - dpi_ratio) * 0.25)

    def resolve(
        self, region: ChatRegion | None, window: WindowIdentity | None
    ) -> ScreenRegion | None:
        if region is None or window is None or window.minimized:
            return None
        if self.compatibility_score(region, window) < 0.7:
            return None
        return normalized_to_screen(region, window.client_bounds)
