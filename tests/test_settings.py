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
