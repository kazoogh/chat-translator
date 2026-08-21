from __future__ import annotations

import re
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
MAX_PATTERN_LENGTH = 256


def validate_safe_regex(pattern: str, *, label: str) -> str:
    """Reject constructs that can turn declarative profile data into a CPU sink."""
    if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"{label} length is invalid")
    without_flag = pattern[4:] if pattern.startswith("(?i)") else pattern
    if re.search(r"\(\?(?!:)", without_flag) or re.search(r"\\[1-9]", without_flag):
        raise ValueError(f"advanced regex constructs are not allowed in {label}")
    _validate_bounded_regex(without_flag, label=label)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{label} is invalid") from exc
    return pattern


def _validate_bounded_regex(pattern: str, *, label: str) -> None:
    """Accept bounded atoms/character classes, but no repeated groups or open-ended repeats."""
    in_class = False
    escaped = False
    index = 0
    repetitions = 0
    while index < len(pattern):
        character = pattern[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == "[":
            in_class = True
            index += 1
            continue
        if character == "]" and in_class:
            in_class = False
            index += 1
            continue
        if not in_class and character in "*+":
            raise ValueError(f"unbounded regex quantifiers are not allowed in {label}")
        if not in_class and character == "?" and (index == 0 or pattern[index - 1] != "("):
            raise ValueError(f"optional regex quantifiers are not allowed in {label}")
        if not in_class and character == "{":
            match = re.match(r"\{(\d+)(?:,(\d*))?\}", pattern[index:])
            if match is None:
                raise ValueError(f"regex repetition is invalid in {label}")
            lower = int(match.group(1))
            upper_text = match.group(2)
            upper = lower if upper_text is None else int(upper_text) if upper_text else None
            repetitions += 1
            if repetitions > 2 or lower < 1 or upper is None or upper > 256 or lower > upper:
                raise ValueError(f"regex repetition exceeds the safe bound in {label}")
            index += len(match.group(0))
            continue
        if (
            not in_class
            and character == ")"
            and index + 1 < len(pattern)
            and pattern[index + 1] in "?*+{"
        ):
            raise ValueError(f"quantified regex groups are not allowed in {label}")
        index += 1


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DetectionRules(ProfileModel):
    executables: tuple[str, ...] = Field(default=(), max_length=64)
    window_title_patterns: tuple[str, ...] = Field(default=(), max_length=64)
    window_class_patterns: tuple[str, ...] = Field(default=(), max_length=64)
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
            validate_safe_regex(value, label="window match pattern")
        return values


class ChatRules(ProfileModel):
    default_anchor: Literal["bottom_left", "bottom_right", "top_left", "top_right"] = "bottom_left"
    player_message_separators: tuple[str, ...] = Field(default=(":",), max_length=16)
    direction_markers: tuple[str, ...] = Field(default=(), max_length=16)
    announce_outbound: bool = False
    announce_system: bool = False
    username_pattern: str = r"^[\w.-]{1,32}$"
    player_colors: tuple[str, ...] = Field(default=(), max_length=32)
    system_colors: tuple[str, ...] = Field(default=(), max_length=32)
    outgoing_colors: tuple[str, ...] = Field(default=(), max_length=32)
    item_link_patterns: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("username_pattern")
    @classmethod
    def safe_username_pattern(cls, value: str) -> str:
        return validate_safe_regex(value, label="username pattern")

    @field_validator("player_message_separators", "direction_markers")
    @classmethod
    def bounded_markers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or len(value) > 16 for value in values):
            raise ValueError("chat separators and markers must contain 1 to 16 characters")
        return values

    @field_validator("player_colors", "system_colors", "outgoing_colors")
    @classmethod
    def valid_chat_colors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None for value in values):
            raise ValueError("chat colors must use #RRGGBB")
        return tuple(value.upper() for value in values)

    @field_validator("item_link_patterns")
    @classmethod
    def safe_item_patterns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_safe_regex(value, label="item link pattern")
        return values


class ResourceRules(ProfileModel):
    glossary_id: str | None = None
    system_patterns: str | None = None

    @field_validator("glossary_id")
    @classmethod
    def safe_glossary_id(cls, value: str | None) -> str | None:
        if value is not None and not PROFILE_ID_PATTERN.fullmatch(value):
            raise ValueError("glossary ID must be a simple resource identifier")
        return value

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
    presets: tuple[str, ...] = Field(default=("default",), max_length=32)


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
