from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from statistics import fmean

from game_chat_translator.models import ChatLine, OcrFragment, Point

_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?%)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([({\[])\s+")


@dataclass(frozen=True, slots=True)
class _FragmentMetrics:
    fragment: OcrFragment
    left: float
    center_y: float
    height: float


def normalize_line(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    normalized = " ".join(normalized.split())
    normalized = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", normalized)
    return _SPACE_AFTER_OPEN.sub(r"\1", normalized).strip()


def comparison_form(text: str) -> str:
    normalized = normalize_line(text).casefold()
    normalized = re.sub(r"([!?.,])\1{2,}", r"\1\1", normalized)
    return normalized


def group_fragments(
    fragments: tuple[OcrFragment, ...], *, minimum_confidence: float = 0.45
) -> tuple[ChatLine, ...]:
    metrics = [
        _metrics(fragment) for fragment in fragments if fragment.confidence >= minimum_confidence
    ]
    metrics.sort(key=lambda item: (item.center_y, item.left))
    groups: list[list[_FragmentMetrics]] = []
    for item in metrics:
        best_group: list[_FragmentMetrics] | None = None
        best_distance = float("inf")
        for group in groups:
            group_center = fmean(member.center_y for member in group)
            group_height = fmean(member.height for member in group)
            distance = abs(item.center_y - group_center)
            if (
                distance <= max(3.0, min(item.height, group_height) * 0.55)
                and distance < best_distance
            ):
                best_group = group
                best_distance = distance
        if best_group is None:
            groups.append([item])
        else:
            best_group.append(item)
    groups.sort(key=lambda group: fmean(item.center_y for item in group))

    lines: list[ChatLine] = []
    for visual_order, group in enumerate(groups):
        group.sort(key=lambda item: item.left)
        raw = _join_fragments([item.fragment.text for item in group])
        if not raw:
            continue
        confidence = fmean(item.fragment.confidence for item in group)
        lines.append(
            ChatLine(
                raw_text=raw,
                normalized_text=normalize_line(raw),
                boxes=tuple(item.fragment.polygon for item in group),
                confidence=confidence,
                visual_order=visual_order,
                colors=tuple(
                    dict.fromkeys(
                        item.fragment.color for item in group if item.fragment.color is not None
                    )
                ),
            )
        )
    return tuple(lines)


def _metrics(fragment: OcrFragment) -> _FragmentMetrics:
    xs = [point.x for point in fragment.polygon]
    ys = [point.y for point in fragment.polygon]
    return _FragmentMetrics(
        fragment=fragment,
        left=min(xs),
        center_y=(min(ys) + max(ys)) / 2,
        height=max(1.0, max(ys) - min(ys)),
    )


def _join_fragments(texts: list[str]) -> str:
    text = " ".join(part.strip() for part in texts if part.strip())
    return normalize_line(text)


def rectangle_polygon(
    left: float, top: float, right: float, bottom: float
) -> tuple[Point, Point, Point, Point]:
    return (
        Point(x=left, y=top),
        Point(x=right, y=top),
        Point(x=right, y=bottom),
        Point(x=left, y=bottom),
    )
