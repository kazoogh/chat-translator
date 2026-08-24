from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_chat_translator.settings import AppSettings, SettingsError, SettingsStore


def test_settings_round_trip_and_backup_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    store = SettingsStore(path)
    first = AppSettings()
    store.save(first)
    changed = first.model_copy(
        update={
            "application": first.application.model_copy(update={"active_profile": "minecraft.java"})
        }
    )
    store.save(changed)
    path.write_text("{broken", encoding="utf-8")

    recovered = store.load()

    assert recovered.application.active_profile == "stalzone.default"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_settings_reject_unknown_fields_and_invalid_backup(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"schema_version": 1, "surprise": true}', encoding="utf-8")
    path.with_suffix(".json.bak").write_text("[]", encoding="utf-8")

    with pytest.raises(SettingsError, match="no valid backup"):
        SettingsStore(path).load()


def test_privacy_defaults_are_local_and_ephemeral() -> None:
    settings = AppSettings()
    assert settings.privacy.persist_message_history is False
    assert settings.privacy.telemetry is False
    assert settings.reply.auto_send is False
    assert settings.reply.suppress_key_event is False


def test_persistent_history_requires_a_bounded_nonzero_retention() -> None:
    with pytest.raises(ValueError, match="retention"):
        AppSettings.model_validate(
            {"privacy": {"persist_message_history": True, "history_retention_days": 0}}
        )
    settings = AppSettings.model_validate(
        {"privacy": {"persist_message_history": True, "history_retention_days": 30}}
    )
    assert settings.privacy.history_retention_days == 30


@pytest.mark.parametrize(
    "speech_recognition",
    [
        {"model": "small"},
        {"model": "remote/repository"},
        {"language": "auto"},
        {"local_only": False},
    ],
)
def test_speech_recognition_cannot_request_remote_or_unallowlisted_models(
    speech_recognition: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        AppSettings.model_validate({"speech_recognition": speech_recognition})


@pytest.mark.parametrize(
    "payload",
    [
        {"reply": {"hold_to_talk": "ctrl+v"}, "hotkeys": {"hold_to_talk": "ctrl+v"}},
        {"hotkeys": {"toggle_capture": "v"}},
        {"hotkeys": {"toggle_capture": "win+t"}},
        {
            "hotkeys": {
                "toggle_capture": "ctrl+shift+t",
                "toggle_speech": "shift+ctrl+t",
            }
        },
        {"hotkeys": {"toggle_capture": "ctrl+shift+v"}},
    ],
)
def test_hotkey_settings_reject_broad_invalid_or_duplicate_observers(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        AppSettings.model_validate(payload)
