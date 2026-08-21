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
        self._declared: dict[str, GameProfile] = {}

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
        self._declared = loaded
        cache: dict[str, GameProfile] = {}
        effective = {
            profile_id: self._resolve_inheritance(profile_id, loaded, cache)
            for profile_id in loaded
        }
        self._profiles = effective
        return dict(effective)

    def resource_directory(self, profile_id: str, field_name: str) -> Path:
        if profile_id not in self._declared:
            raise KeyError(f"unknown profile: {profile_id}")
        current = self._declared[profile_id]
        while True:
            if field_name in current.resources.model_fields_set:
                return self.root / current.profile_id
            if current.inherits is None:
                return self.root / current.profile_id
            current = self._declared[current.inherits]

    def _load_file(self, path: Path) -> GameProfile:
        if path.is_symlink() or path.parent.is_symlink():
            raise ProfileLoadError("profile path cannot be a symbolic link")
        resolved = path.resolve()
        if self.root not in resolved.parents:
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

    def _resolve_inheritance(
        self,
        profile_id: str,
        profiles: dict[str, GameProfile],
        cache: dict[str, GameProfile],
    ) -> GameProfile:
        if profile_id in cache:
            return cache[profile_id]
        declared = profiles[profile_id]
        if declared.inherits is None:
            cache[profile_id] = declared
            return declared
        parent = self._resolve_inheritance(declared.inherits, profiles, cache)
        payload = _deep_merge(
            parent.model_dump(mode="python"), declared.model_dump(exclude_unset=True)
        )
        payload["profile_id"] = declared.profile_id
        payload["inherits"] = declared.inherits
        effective = GameProfile.model_validate(payload)
        cache[profile_id] = effective
        return effective


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
