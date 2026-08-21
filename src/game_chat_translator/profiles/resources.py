from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from game_chat_translator.profiles.loader import ProfileLoadError, ProfileRegistry
from game_chat_translator.profiles.overrides import ProfileOverride, apply_profile_override
from game_chat_translator.profiles.schema import GameProfile, validate_safe_regex
from game_chat_translator.validation.schemas import GlossaryFile
from game_chat_translator.validation.validators import validate_glossary


class SystemPatternFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    patterns: tuple[str, ...] = Field(max_length=64)


@dataclass(frozen=True, slots=True)
class ProfileResources:
    profile: GameProfile
    system_patterns: tuple[re.Pattern[str], ...]
    glossary: GlossaryFile | None

    def matches_system(self, text: str) -> bool:
        bounded = text[:512]
        return any(pattern.search(bounded) is not None for pattern in self.system_patterns)


class ResourceRegistry:
    def __init__(
        self, root: Path, *, overrides: Mapping[str, ProfileOverride] | None = None
    ) -> None:
        self._root = root.resolve()
        self._profiles = ProfileRegistry(self._root / "profiles")
        self._resources: dict[str, ProfileResources] = {}
        self._overrides = dict(overrides or {})

    def load_all(self) -> dict[str, ProfileResources]:
        profiles = self._profiles.load_all()
        unknown_overrides = set(self._overrides) - set(profiles)
        if unknown_overrides:
            raise ProfileLoadError(
                f"profile overrides target unknown IDs: {sorted(unknown_overrides)!r}"
            )
        resources = {}
        for profile_id, profile in profiles.items():
            override = self._overrides.get(profile_id)
            effective = (
                apply_profile_override(profile, override) if override is not None else profile
            )
            resources[profile_id] = self._load_profile_resources(effective)
        self._resources = resources
        return dict(resources)

    def get(self, profile_id: str) -> ProfileResources:
        try:
            return self._resources[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown profile resources: {profile_id}") from exc

    def _load_profile_resources(self, profile: GameProfile) -> ProfileResources:
        directory = self._profiles.resource_directory(profile.profile_id, "system_patterns")
        patterns: tuple[re.Pattern[str], ...] = ()
        if profile.resources.system_patterns is not None:
            resource_root = directory.resolve()
            unresolved = resource_root / profile.resources.system_patterns
            try:
                path = unresolved.resolve(strict=True)
                if (
                    resource_root not in path.parents
                    or unresolved.is_symlink()
                    or not path.is_file()
                ):
                    raise ProfileLoadError("system pattern resource path is unsafe")
                if path.stat().st_size > 262_144:
                    raise ProfileLoadError("system pattern resource is too large")
                parsed = SystemPatternFile.model_validate_json(path.read_text(encoding="utf-8"))
                patterns = tuple(_compile_safe_pattern(pattern) for pattern in parsed.patterns)
            except (OSError, UnicodeError, ValidationError, ValueError) as exc:
                raise ProfileLoadError(
                    f"profile {profile.profile_id} has invalid system patterns"
                ) from exc
        glossary: GlossaryFile | None = None
        if profile.resources.glossary_id is not None:
            glossary_root = (self._root / "data" / "glossaries").resolve()
            unresolved = glossary_root / f"{profile.resources.glossary_id}.json"
            try:
                path = unresolved.resolve(strict=True)
                if (
                    glossary_root not in path.parents
                    or unresolved.is_symlink()
                    or not path.is_file()
                ):
                    raise ProfileLoadError("glossary resource path is unsafe")
                glossary = validate_glossary(path)
            except (OSError, RuntimeError) as exc:
                raise ProfileLoadError(
                    f"profile {profile.profile_id} has an invalid glossary resource"
                ) from exc
        return ProfileResources(profile, patterns, glossary)


def _compile_safe_pattern(pattern: str) -> re.Pattern[str]:
    validate_safe_regex(pattern, label="system pattern")
    return re.compile(pattern)
