from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SETTINGS_SCHEMA_VERSION: Literal[1] = 1
MAX_SETTINGS_BYTES = 1_048_576


class SettingsError(RuntimeError):
    """A safe, actionable configuration error."""


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationSettings(SettingsModel):
    close_to_tray: bool = True
    start_with_windows: bool = False
    active_profile: str = "stalzone.default"
    auto_detect_game: bool = True
    profile_switch_debounce_ms: int = Field(default=1200, ge=0, le=30_000)
    pause_when_no_game_focused: bool = True


class CaptureSettings(SettingsModel):
    backend: Literal["dxcam", "mss", "mock"] = "dxcam"
    monitor: int = Field(default=0, ge=0)
    interval_ms: int = Field(default=500, ge=100, le=10_000)
    region_coordinate_space: Literal["game_client_normalized"] = "game_client_normalized"


class OcrSettings(SettingsModel):
    scripts: list[str] = Field(default_factory=lambda: ["cyrillic", "latin"])
    preferred_languages: list[str] = Field(default_factory=lambda: ["ru", "en", "tr"])
    minimum_confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    preprocess_profile: str = "profile_default"


class TranslationSettings(SettingsModel):
    enabled: bool = True
    mode: Literal["local_contextual", "lightweight_offline", "untranslated"] = "local_contextual"
    provider: str = "llama_cpp"
    model_id: str = "auto"
    source: str = "auto"
    target: str = "en"
    style: Literal["natural_gamer"] = "natural_gamer"
    context_messages: int = Field(default=6, ge=3, le=10)
    preserve_profanity: bool = True
    show_literal_translation: bool = False
    glossary: str = "profile_default"


class LearningSettings(SettingsModel):
    enabled: bool = True
    automatic_existing_term_aliases: bool = True
    minimum_distinct_occurrences: int = Field(default=3, ge=2, le=100)
    minimum_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    confirm_new_canonical_terms: bool = True
    share_candidates: Literal[False] = False


class ReplySettings(SettingsModel):
    enabled: bool = True
    delivery: Literal["clipboard"] = "clipboard"
    copy_after_translation: bool = True
    default_target: Literal["last_inbound_speaker"] = "last_inbound_speaker"
    require_target_confirmation_when_ambiguous: bool = True
    auto_send: Literal[False] = False
    hold_to_talk: str = Field(default="v", min_length=1, max_length=3)
    minimum_hold_ms: int = Field(default=180, ge=100, le=5000)
    suppress_key_event: Literal[False] = False
    show_clipboard_toast: bool = True

    @model_validator(mode="after")
    def valid_hold_key(self) -> ReplySettings:
        _validate_observed_key(self.hold_to_talk)
        return self


class SpeechRecognitionSettings(SettingsModel):
    provider: Literal["faster_whisper"] = "faster_whisper"
    model: Literal["faster-whisper-small.en-local"] = "faster-whisper-small.en-local"
    language: Literal["en"] = "en"
    local_only: Literal[True] = True
    minimum_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    maximum_recording_seconds: float = Field(default=30.0, ge=1.0, le=30.0)
    microphone_device: str | int | None = None


class SpeechSettings(SettingsModel):
    enabled: bool = True
    rate: int = Field(default=185, ge=50, le=400)
    volume: float = Field(default=0.9, ge=0.0, le=1.0)
    voice_id: str | None = Field(default=None, max_length=500)


class PrivacySettings(SettingsModel):
    persist_message_history: bool = False
    history_retention_days: int = Field(default=0, ge=0, le=365)
    diagnostic_text_logging: bool = False
    save_debug_frames: bool = False
    telemetry: Literal[False] = False

    @model_validator(mode="after")
    def retention_requires_history(self) -> PrivacySettings:
        if self.persist_message_history and self.history_retention_days == 0:
            raise ValueError("enabled history requires a retention period")
        if not self.persist_message_history and self.history_retention_days != 0:
            raise ValueError("history retention must be zero when persistence is disabled")
        return self


class HotkeySettings(SettingsModel):
    toggle_capture: str = Field(default="ctrl+shift+t", max_length=40)
    toggle_speech: str = Field(default="ctrl+shift+m", max_length=40)
    clear_history: str = Field(default="ctrl+shift+l", max_length=40)
    hold_to_talk: str = Field(default="v", min_length=1, max_length=3)

    @model_validator(mode="after")
    def valid_observation_only_shortcuts(self) -> HotkeySettings:
        shortcuts = (self.toggle_capture, self.toggle_speech, self.clear_history)
        normalized = tuple(_validate_shortcut(value) for value in shortcuts)
        if len(set(normalized)) != len(normalized):
            raise ValueError("global shortcuts must be unique")
        _validate_observed_key(self.hold_to_talk)
        return self


class AppSettings(SettingsModel):
    schema_version: Literal[1] = SETTINGS_SCHEMA_VERSION
    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    capture: CaptureSettings = Field(default_factory=CaptureSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    translation: TranslationSettings = Field(default_factory=TranslationSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    reply: ReplySettings = Field(default_factory=ReplySettings)
    speech_recognition: SpeechRecognitionSettings = Field(default_factory=SpeechRecognitionSettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    hotkeys: HotkeySettings = Field(default_factory=HotkeySettings)

    @model_validator(mode="after")
    def hotkey_consistency(self) -> AppSettings:
        if _validate_observed_key(self.hotkeys.hold_to_talk) != _validate_observed_key(
            self.reply.hold_to_talk
        ):
            raise ValueError("reply and hotkey hold-to-talk values must match")
        hold = _validate_observed_key(self.reply.hold_to_talk)
        if any(
            hold in _validate_shortcut(shortcut)
            for shortcut in (
                self.hotkeys.toggle_capture,
                self.hotkeys.toggle_speech,
                self.hotkeys.clear_history,
            )
        ):
            raise ValueError("hold-to-talk cannot share a key with a global shortcut")
        return self


def default_data_dir() -> Path:
    return Path(user_data_path("GameChatTranslator", appauthor=False, roaming=False))


def _validate_observed_key(value: str) -> str:
    key = value.strip().upper()
    if len(key) == 1 and key.isascii() and key.isalnum():
        return key
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return key
    raise ValueError("hold-to-talk key must be A-Z, 0-9, or F1-F12")


def _validate_shortcut(value: str) -> tuple[str, ...]:
    parts = tuple(part.strip().upper() for part in value.split("+") if part.strip())
    if not 2 <= len(parts) <= 4 or len(set(parts)) != len(parts):
        raise ValueError("global shortcut must be a unique modifier chord")
    if any(part not in {"CTRL", "SHIFT", "ALT"} for part in parts[:-1]):
        raise ValueError("global shortcut modifiers are invalid")
    _validate_observed_key(parts[-1])
    return tuple(sorted(parts))


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_data_dir() / "config.json"
        self.backup_path = self.path.with_suffix(".json.bak")

    def load(self) -> AppSettings:
        if not self.path.exists():
            settings = AppSettings()
            self.save(settings)
            return settings
        try:
            return self._read_validated(self.path)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            SettingsError,
        ) as primary:
            if self.backup_path.exists():
                try:
                    recovered = self._read_validated(self.backup_path)
                    self._write_atomic(self.path, recovered.model_dump(mode="json"), rotate=False)
                    return recovered
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    ValidationError,
                    SettingsError,
                ):
                    pass
            raise SettingsError(
                "Configuration is invalid and no valid backup is available; move config.json "
                "aside to recreate defaults."
            ) from primary

    def save(self, settings: AppSettings) -> None:
        self._write_atomic(self.path, settings.model_dump(mode="json"), rotate=True)

    def _read_validated(self, path: Path) -> AppSettings:
        size = path.stat().st_size
        if size > MAX_SETTINGS_BYTES:
            raise SettingsError(f"Configuration exceeds {MAX_SETTINGS_BYTES} bytes")
        with path.open("r", encoding="utf-8") as handle:
            payload: Any = json.load(handle)
        return AppSettings.model_validate(payload)

    def _write_atomic(self, path: Path, payload: dict[str, Any], *, rotate: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        try:
            with temp_path.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if rotate and path.exists():
                os.replace(path, self.backup_path)
            os.replace(temp_path, path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            if rotate and not path.exists() and self.backup_path.exists():
                os.replace(self.backup_path, path)
            raise SettingsError("Could not save configuration atomically") from exc
