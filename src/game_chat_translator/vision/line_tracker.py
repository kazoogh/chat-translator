from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

from game_chat_translator.models import ChatLine
from game_chat_translator.vision.line_grouping import comparison_form


@dataclass(frozen=True, slots=True)
class _RecentEmission:
    comparison: str
    emitted_at: float


class LineTracker:
    def __init__(
        self,
        *,
        similarity_threshold: float = 0.88,
        expiry_seconds: float = 12.0,
        max_recent: int = 256,
        max_visual_displacement: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity threshold must be between zero and one")
        if expiry_seconds <= 0 or max_recent <= 0 or max_visual_displacement < 0:
            raise ValueError("line tracker limits must be positive")
        self._threshold = similarity_threshold
        self._expiry_seconds = expiry_seconds
        self._max_visual_displacement = max_visual_displacement
        self._clock = clock
        self._previous: tuple[ChatLine, ...] = ()
        self._recent: deque[_RecentEmission] = deque(maxlen=max_recent)
        self._generation: int | None = None

    def accept(self, lines: tuple[ChatLine, ...], *, generation: int) -> tuple[ChatLine, ...]:
        if self._generation != generation:
            self.reset(generation=generation)
        now = self._clock()
        self._expire(now)
        unmatched = self._unmatched_current(lines)
        previous_counts = Counter(comparison_form(line.normalized_text) for line in self._previous)
        current_counts: Counter[str] = Counter()
        emitted_counts: Counter[str] = Counter()
        emitted: list[ChatLine] = []
        for index, line in enumerate(lines):
            current_counts[comparison_form(line.normalized_text)] += 1
            if index not in unmatched:
                continue
            form = comparison_form(line.normalized_text)
            occurrence_added = current_counts[form] > previous_counts[form]
            recently_seen = any(form == item.comparison for item in self._recent)
            if recently_seen and not (
                (previous_counts[form] > 0 and occurrence_added) or emitted_counts[form] > 0
            ):
                continue
            emitted.append(line)
            emitted_counts[form] += 1
            self._recent.append(_RecentEmission(form, now))
        self._previous = lines
        return tuple(emitted)

    def reset(self, *, generation: int | None = None) -> None:
        self._previous = ()
        self._recent.clear()
        self._generation = generation

    @property
    def recent_size(self) -> int:
        return len(self._recent)

    def _unmatched_current(self, current: tuple[ChatLine, ...]) -> set[int]:
        previous_count = len(self._previous)
        current_count = len(current)
        scores = [[0.0] * (current_count + 1) for _ in range(previous_count + 1)]
        matched = [[False] * (current_count + 1) for _ in range(previous_count + 1)]
        for previous_index in range(1, previous_count + 1):
            for current_index in range(1, current_count + 1):
                previous = self._previous[previous_index - 1]
                candidate = current[current_index - 1]
                similarity = _similarity(previous.normalized_text, candidate.normalized_text)
                can_match = (
                    abs(previous.visual_order - candidate.visual_order)
                    <= self._max_visual_displacement
                    and similarity >= self._threshold
                )
                diagonal = scores[previous_index - 1][current_index - 1] + (
                    similarity if can_match else -1.0
                )
                above = scores[previous_index - 1][current_index]
                left = scores[previous_index][current_index - 1]
                if can_match and diagonal >= above and diagonal > left:
                    scores[previous_index][current_index] = diagonal
                    matched[previous_index][current_index] = True
                else:
                    scores[previous_index][current_index] = max(above, left)

        matched_current: set[int] = set()
        previous_index, current_index = previous_count, current_count
        while previous_index and current_index:
            if matched[previous_index][current_index]:
                matched_current.add(current_index - 1)
                previous_index -= 1
                current_index -= 1
            elif (
                scores[previous_index - 1][current_index]
                >= scores[previous_index][current_index - 1]
            ):
                previous_index -= 1
            else:
                current_index -= 1
        return set(range(current_count)) - matched_current

    def _expire(self, now: float) -> None:
        while self._recent and now - self._recent[0].emitted_at >= self._expiry_seconds:
            self._recent.popleft()


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, comparison_form(left), comparison_form(right), autojunk=False
    ).ratio()
