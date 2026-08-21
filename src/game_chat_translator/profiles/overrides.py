from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from game_chat_translator.profiles.loader import _deep_merge
from game_chat_translator.profiles.schema import GameProfile


class OverrideModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DetectionOverride(OverrideModel):
    executables: tuple[str, ...] | None = None
    window_title_patterns: tuple[str, ...] | None = None
    window_class_patterns: tuple[str, ...] | None = None
    minimum_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ChatOverride(OverrideModel):
    player_message_separators: tuple[str, ...] | None = None
    direction_markers: tuple[str, ...] | None = None
    username_pattern: str | None = None
    player_colors: tuple[str, ...] | None = None
    system_colors: tuple[str, ...] | None = None
    outgoing_colors: tuple[str, ...] | None = None
    item_link_patterns: tuple[str, ...] | None = None
    announce_outbound: bool | None = None
    announce_system: bool | None = None


class LayoutOverride(OverrideModel):
    default_anchor: str | None = None
    presets: tuple[str, ...] | None = None


class PreprocessOverride(OverrideModel):
    scale: int | None = Field(default=None, ge=1, le=4)
    contrast: float | None = Field(default=None, ge=0.1, le=5.0)
    sharpen: bool | None = None
    text_colors: tuple[str, ...] | None = None


class ProfileOverride(OverrideModel):
    schema_version: Literal[1] = 1
    profile_id: str
    detection: DetectionOverride | None = None
    chat: ChatOverride | None = None
    layouts: LayoutOverride | None = None
    preprocess: PreprocessOverride | None = None


def parse_profile_override(data: bytes) -> ProfileOverride:
    if len(data) > 262_144:
        raise ValueError("profile override exceeds the size limit")
    return ProfileOverride.model_validate_json(data)


def export_profile_override(override: ProfileOverride) -> bytes:
    encoded = (override.model_dump_json(indent=2) + "\n").encode("utf-8")
    if len(encoded) > 262_144:
        raise ValueError("profile override exceeds the size limit")
    return encoded


def apply_profile_override(profile: GameProfile, override: ProfileOverride) -> GameProfile:
    if override.profile_id != profile.profile_id:
        raise ValueError("profile override ID does not match the target profile")
    changes = override.model_dump(
        mode="python", exclude_none=True, exclude={"schema_version", "profile_id"}
    )
    payload = _deep_merge(profile.model_dump(mode="python"), changes)
    return GameProfile.model_validate(payload)
