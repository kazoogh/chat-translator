from __future__ import annotations

import re
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
MAX_PATTERN_LENGTH = 256


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DetectionRules(ProfileModel):
    executables: tuple[str, ...] = ()
    window_title_patterns: tuple[str, ...] = ()
    window_class_patterns: tuple[str, ...] = ()
    minimum_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    status: str = "ready"

    @field_validator("executables")
    @classmethod
    def executable_basenames_only(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value or PurePath(value).name != value or "/" in value or "\\" in value:
                raise ValueError("profile executable matchers must be basenames")
        return values

    @field_validator("window_title_patterns", "window_class_patterns")
    @classmethod
    def bounded_patterns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if len(value) > MAX_PATTERN_LENGTH:
                raise ValueError("window match pattern is too long")
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError("window match pattern is invalid") from exc
        return values


class ChatRules(ProfileModel):
    default_anchor: Literal["bottom_left", "bottom_right", "top_left", "top_right"] = "bottom_left"
    player_message_separators: tuple[str, ...] = (":",)
    direction_markers: tuple[str, ...] = ()
    announce_outbound: bool = False
    announce_system: bool = False
    username_pattern: str = r"^[\w.-]{1,32}$"

    @field_validator("username_pattern")
    @classmethod
    def safe_username_pattern(cls, value: str) -> str:
        if len(value) > MAX_PATTERN_LENGTH:
            raise ValueError("username pattern is too long")
        re.compile(value)
        return value


class ResourceRules(ProfileModel):
    glossary_id: str | None = None
    system_patterns: str | None = None

    @field_validator("system_patterns")
    @classmethod
    def relative_resource(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePath(value)
        if path.is_absolute() or ".." in path.parts or path.name != value:
            raise ValueError("profile resource must be a simple relative filename")
        return value


class LayoutRules(ProfileModel):
    strategy: Literal["manual", "user_calibration_with_profile_hints"] = "manual"
    default_anchor: Literal["bottom_left", "bottom_right", "top_left", "top_right"] = "bottom_left"
    presets: tuple[str, ...] = ("default",)


class PreprocessRules(ProfileModel):
    scale: int = Field(default=2, ge=1, le=4)
    contrast: float = Field(default=1.2, ge=0.1, le=5.0)
    sharpen: bool = True
    text_colors: tuple[str, ...] = ()

    @field_validator("text_colors")
    @classmethod
    def valid_text_colors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None for value in values):
            raise ValueError("preprocess text colors must use #RRGGBB")
        return values


class GameProfile(ProfileModel):
    schema_version: Literal[1]
    profile_id: str
    version: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=80)
    inherits: str | None = None
    detection: DetectionRules = Field(default_factory=DetectionRules)
    chat: ChatRules = Field(default_factory=ChatRules)
    resources: ResourceRules = Field(default_factory=ResourceRules)
    layouts: LayoutRules = Field(default_factory=LayoutRules)
    preprocess: PreprocessRules = Field(default_factory=PreprocessRules)

    @field_validator("profile_id", "inherits")
    @classmethod
    def valid_profile_id(cls, value: str | None) -> str | None:
        if value is not None and not PROFILE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid profile ID")
        return value
