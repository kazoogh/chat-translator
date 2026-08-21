from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from game_chat_translator.profiles.schema import GameProfile


class ProfileLoadError(RuntimeError):
    pass


MAX_PROFILE_BYTES = 262_144


class ProfileRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._profiles: dict[str, GameProfile] = {}

    @property
    def profiles(self) -> dict[str, GameProfile]:
        return dict(self._profiles)

    def load_all(self) -> dict[str, GameProfile]:
        loaded: dict[str, GameProfile] = {}
        for path in sorted(self.root.glob("*/profile.json")):
            profile = self._load_file(path)
            if profile.profile_id in loaded:
                raise ProfileLoadError(f"duplicate profile ID: {profile.profile_id}")
            if path.parent.name != profile.profile_id:
                raise ProfileLoadError(f"profile directory must match ID: {profile.profile_id}")
            self._validate_resources(path.parent, profile)
            loaded[profile.profile_id] = profile
        for profile_id in loaded:
            self._validate_inheritance(profile_id, loaded, ())
        self._profiles = loaded
        return dict(loaded)

    def _load_file(self, path: Path) -> GameProfile:
        resolved = path.resolve()
        if self.root not in resolved.parents or resolved.is_symlink():
            raise ProfileLoadError("profile path escapes the registry root")
        if path.stat().st_size > MAX_PROFILE_BYTES:
            raise ProfileLoadError("profile is too large")
        try:
            with path.open("r", encoding="utf-8") as handle:
                return GameProfile.model_validate(json.load(handle))
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
            raise ProfileLoadError(f"invalid profile: {path.name}") from exc

    def _validate_resources(self, directory: Path, profile: GameProfile) -> None:
        if profile.resources.system_patterns is None:
            return
        candidate = (directory / profile.resources.system_patterns).resolve()
        if directory.resolve() not in candidate.parents or not candidate.is_file():
            raise ProfileLoadError(
                f"profile {profile.profile_id} references a missing or unsafe resource"
            )

    def _validate_inheritance(
        self, profile_id: str, profiles: dict[str, GameProfile], chain: tuple[str, ...]
    ) -> None:
        if profile_id in chain:
            raise ProfileLoadError("profile inheritance cycle detected")
        parent = profiles[profile_id].inherits
        if parent is None:
            return
        if parent not in profiles:
            raise ProfileLoadError(f"profile {profile_id} inherits missing profile {parent}")
        self._validate_inheritance(parent, profiles, (*chain, profile_id))
