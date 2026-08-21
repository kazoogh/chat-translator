from __future__ import annotations

import math
from collections import Counter

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import OcrFragment, Point


def attach_source_colors(
    fragments: tuple[OcrFragment, ...],
    frame: RawFrame,
    *,
    preprocess_scale: int,
    candidate_colors: tuple[str, ...],
    tolerance: int,
) -> tuple[OcrFragment, ...]:
    """Attach the closest configured source-frame color to each OCR polygon."""
    if frame.pixel_format != "BGRA" or not candidate_colors or not fragments:
        return fragments
    candidates = tuple((color.upper(), _parse_color(color)) for color in candidate_colors)
    output: list[OcrFragment] = []
    for fragment in fragments:
        counts: Counter[str] = Counter()
        polygon = fragment.polygon
        left = max(0, math.floor(min(point.x for point in polygon) / preprocess_scale))
        right = min(frame.width, math.ceil(max(point.x for point in polygon) / preprocess_scale))
        top = max(0, math.floor(min(point.y for point in polygon) / preprocess_scale))
        bottom = min(frame.height, math.ceil(max(point.y for point in polygon) / preprocess_scale))
        area = max(1, (right - left) * (bottom - top))
        stride = max(1, math.ceil(math.sqrt(area / 4_096)))
        for y in range(top, bottom, stride):
            for x in range(left, right, stride):
                processed_point = Point(
                    x=(x + 0.5) * preprocess_scale,
                    y=(y + 0.5) * preprocess_scale,
                )
                if not _inside_polygon(processed_point, polygon):
                    continue
                offset = (y * frame.width + x) * 4
                blue, green, red = frame.pixels[offset : offset + 3]
                closest = min(
                    candidates,
                    key=lambda candidate: _distance((red, green, blue), candidate[1]),
                )
                if _distance((red, green, blue), closest[1]) <= tolerance:
                    counts[closest[0]] += 1
        color = counts.most_common(1)[0][0] if counts else None
        output.append(fragment.model_copy(update={"color": color}))
    return tuple(output)


def _parse_color(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def _inside_polygon(point: Point, polygon: tuple[Point, Point, Point, Point]) -> bool:
    inside = False
    prior = polygon[-1]
    for current in polygon:
        crosses = (current.y > point.y) != (prior.y > point.y)
        if crosses:
            boundary_x = (prior.x - current.x) * (point.y - current.y) / (
                prior.y - current.y
            ) + current.x
            if point.x < boundary_x:
                inside = not inside
        prior = current
    return inside
