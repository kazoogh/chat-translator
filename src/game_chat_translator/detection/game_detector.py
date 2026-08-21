from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from game_chat_translator.models import WindowIdentity
from game_chat_translator.profiles.schema import GameProfile


@dataclass(frozen=True, slots=True)
class ProfileResolution:
    profile_id: str | None
    confidence: float
    stable: bool
    pinned: bool
    should_pause: bool
    reason: str


class ProfileResolver:
    def __init__(
        self,
        profiles: Mapping[str, GameProfile],
        *,
        debounce_seconds: float = 1.2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._profiles = dict(profiles)
        self._debounce_seconds = debounce_seconds
        self._clock = clock
        self._candidate: tuple[str, int] | None = None
        self._candidate_since = 0.0
        self._active: str | None = None
        self._pinned: str | None = None

    def pin(self, profile_id: str | None) -> None:
        if profile_id is not None and profile_id not in self._profiles:
            raise KeyError(f"unknown profile: {profile_id}")
        self._pinned = profile_id
        self._candidate = None

    def resolve(self, window: WindowIdentity | None) -> ProfileResolution:
        if self._pinned is not None:
            self._active = self._pinned
            return ProfileResolution(
                self._pinned, 1.0, True, True, False, "manual profile override"
            )
        if window is None or window.minimized:
            self._active = None
            self._candidate = None
            return ProfileResolution(None, 0.0, True, False, True, "no usable foreground window")

        matches = [self._score(profile, window) for profile in self._profiles.values()]
        eligible = [item for item in matches if item[1] >= item[0].detection.minimum_confidence]
        if not eligible:
            self._active = None
            self._candidate = None
            return ProfileResolution(None, 0.0, True, False, True, "unknown foreground game")

        profile, confidence = max(eligible, key=lambda item: item[1])
        now = self._clock()
        candidate = (profile.profile_id, window.process_id)
        if candidate != self._candidate:
            self._candidate = candidate
            self._candidate_since = now
            return ProfileResolution(None, confidence, False, False, True, "candidate debouncing")
        if now - self._candidate_since < self._debounce_seconds:
            return ProfileResolution(None, confidence, False, False, True, "candidate debouncing")
        self._active = profile.profile_id
        return ProfileResolution(self._active, confidence, True, False, False, "profile matched")

    @staticmethod
    def _score(profile: GameProfile, window: WindowIdentity) -> tuple[GameProfile, float]:
        rules = profile.detection
        executable = window.executable.casefold()
        score = 0.0
        if rules.executables and executable in {value.casefold() for value in rules.executables}:
            score += 0.55
        title_match = bool(rules.window_title_patterns) and any(
            re.search(pattern, window.title[:1024]) for pattern in rules.window_title_patterns
        )
        if title_match:
            score += 0.35
            if not rules.executables:
                score += 0.55
        if rules.window_class_patterns and any(
            re.search(pattern, window.window_class[:256]) for pattern in rules.window_class_patterns
        ):
            score += 0.10
        return profile, min(score, 1.0)
