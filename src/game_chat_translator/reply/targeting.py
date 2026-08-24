from __future__ import annotations

import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from game_chat_translator.reply.base import ReplyTarget

_COMMAND = re.compile(r"^\s*reply\s+to\s+([^:\n]{1,200})\s*:\s*(.{1,8192})\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedReply:
    body: str
    requested_target: str | None = None

    def __post_init__(self) -> None:
        if not self.body.strip() or len(self.body) > 8_192:
            raise ValueError("reply body is blank or exceeds its bound")


class TargetResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_TARGET = "needs_target"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class TargetResolution:
    status: TargetResolutionStatus
    target: ReplyTarget | None = None
    candidates: tuple[ReplyTarget, ...] = ()


class SpeakerTracker:
    """Bounded in-memory speaker/language recency with opaque caller-owned IDs."""

    def __init__(
        self,
        *,
        capacity: int = 64,
        maximum_age_seconds: float = 600.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0 or maximum_age_seconds <= 0:
            raise ValueError("speaker capacity and maximum age must be positive")
        self._capacity = capacity
        self._maximum_age = maximum_age_seconds
        self._monotonic = monotonic
        self._targets: dict[str, ReplyTarget] = {}
        self._observed: dict[str, float] = {}
        self._name_ids: dict[str, UUID] = {}
        self._order: deque[str] = deque()
        self._last: str | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def observe(self, target: ReplyTarget) -> None:
        speaker_id = str(target.speaker_id)
        if speaker_id in self._targets:
            self._order.remove(speaker_id)
        self._targets[speaker_id] = target
        self._observed[speaker_id] = self._monotonic()
        self._name_ids.setdefault(_normalize_name(target.display_name), target.speaker_id)
        self._order.append(speaker_id)
        self._last = speaker_id
        while len(self._order) > self._capacity:
            removed = self._order.popleft()
            removed_target = self._targets.pop(removed, None)
            self._observed.pop(removed, None)
            if removed_target is not None:
                normalized = _normalize_name(removed_target.display_name)
                if self._name_ids.get(normalized) == removed_target.speaker_id:
                    self._name_ids.pop(normalized, None)
        self._generation += 1

    def observe_message(
        self,
        display_name: str,
        language: str,
        confidence: float,
    ) -> ReplyTarget:
        normalized = _normalize_name(display_name)
        if not normalized:
            raise ValueError("speaker display name is invalid")
        identity = self._name_ids.get(normalized, uuid4())
        target = ReplyTarget(identity, display_name.strip(), language, confidence)
        self.observe(target)
        return target

    def clear(self) -> None:
        self._targets.clear()
        self._observed.clear()
        self._name_ids.clear()
        self._order.clear()
        self._last = None
        self._generation += 1

    def get(self, speaker_id: UUID) -> ReplyTarget | None:
        self._purge_stale()
        return self._targets.get(str(speaker_id))

    def candidates(self) -> tuple[ReplyTarget, ...]:
        self._purge_stale()
        return tuple(self._targets[identity] for identity in reversed(self._order))

    def resolve(self, requested_name: str | None = None) -> TargetResolution:
        self._purge_stale()
        if requested_name is None:
            target = self._targets.get(self._last) if self._last is not None else None
            return TargetResolution(
                TargetResolutionStatus.RESOLVED
                if target is not None
                else TargetResolutionStatus.NEEDS_TARGET,
                target,
            )
        key = _normalize_name(requested_name)
        matches = tuple(
            target
            for target in self._targets.values()
            if _normalize_name(target.display_name) == key
        )
        if len(matches) == 1:
            return TargetResolution(TargetResolutionStatus.RESOLVED, matches[0])
        if len(matches) > 1:
            return TargetResolution(TargetResolutionStatus.AMBIGUOUS, candidates=matches)
        return TargetResolution(TargetResolutionStatus.NEEDS_TARGET)

    def _purge_stale(self) -> None:
        cutoff = self._monotonic() - self._maximum_age
        stale = tuple(
            identity for identity, observed in self._observed.items() if observed < cutoff
        )
        if not stale:
            return
        for identity in stale:
            target = self._targets.pop(identity, None)
            self._observed.pop(identity, None)
            if identity in self._order:
                self._order.remove(identity)
            if target is not None:
                normalized = _normalize_name(target.display_name)
                if self._name_ids.get(normalized) == target.speaker_id:
                    self._name_ids.pop(normalized, None)
        if self._last in stale:
            self._last = self._order[-1] if self._order else None
        self._generation += 1


def parse_reply_command(transcript: str) -> ParsedReply:
    if not transcript.strip() or len(transcript) > 8_192:
        raise ValueError("reply transcript is blank or exceeds its bound")
    match = _COMMAND.fullmatch(transcript)
    if match is None:
        return ParsedReply(transcript.strip())
    target, body = match.groups()
    return ParsedReply(body.strip(), target.strip())


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
