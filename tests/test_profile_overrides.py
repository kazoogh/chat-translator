from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from game_chat_translator.classification.classifier import MessageClassifier
from game_chat_translator.models import ChatLine, MessageClass
from game_chat_translator.profiles.loader import ProfileRegistry
from game_chat_translator.profiles.overrides import (
    ProfileOverride,
    export_profile_override,
    parse_profile_override,
)
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.profiles.schema import GameProfile
from game_chat_translator.storage.database import Database
from game_chat_translator.storage.repositories import SqliteStateRepository

ROOT = Path(__file__).resolve().parents[1]


def test_user_override_changes_effective_profile_without_mutating_bundled_file() -> None:
    path = ROOT / "profiles" / "stalzone.default" / "profile.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    override = ProfileOverride.model_validate(
        {
            "schema_version": 1,
            "profile_id": "stalzone.default",
            "chat": {"player_message_separators": ["|"]},
        }
    )
    resources = ResourceRegistry(ROOT, overrides={"stalzone.default": override}).load_all()[
        "stalzone.default"
    ]
    classifier = MessageClassifier(resources)
    decision = classifier.classify(
        ChatLine(
            raw_text="Vasya|привет",
            normalized_text="Vasya|привет",
            confidence=0.95,
            visual_order=0,
        )
    )
    assert decision.message.classification is MessageClass.PLAYER_INBOUND
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_profile_override_survives_database_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    override = ProfileOverride.model_validate(
        {
            "schema_version": 1,
            "profile_id": "minecraft.java",
            "preprocess": {"scale": 3},
        }
    )
    with Database(path) as database:
        SqliteStateRepository(database).save_profile_override(override)
    with Database(path) as database:
        reopened = SqliteStateRepository(database).load_profile_override("minecraft.java")
    assert reopened == override
    assert reopened is not None and reopened.preprocess is not None
    assert reopened.preprocess.scale == 3


def test_profile_override_export_import_is_versioned_and_bounded() -> None:
    override = ProfileOverride(
        profile_id="stalzone.default",
        chat={"player_message_separators": ("|",)},
    )
    assert parse_profile_override(export_profile_override(override)) == override
    with pytest.raises(ValueError, match="size limit"):
        parse_profile_override(b"x" * 262_145)
    with pytest.raises(ValueError):
        parse_profile_override(b'{"schema_version":2,"profile_id":"stalzone.default"}')


def test_profile_inheritance_merges_only_declared_child_fields(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    generic = root / "generic.test"
    child = root / "child.test"
    generic.mkdir(parents=True)
    child.mkdir()
    generic_payload = {
        "schema_version": 1,
        "profile_id": "generic.test",
        "version": 1,
        "display_name": "Generic",
        "chat": {
            "player_message_separators": [":"],
            "username_pattern": "^[A-Z][A-Za-z]{1,15}$",
            "player_colors": ["#FFFFFF"],
        },
    }
    child_payload = {
        "schema_version": 1,
        "profile_id": "child.test",
        "version": 1,
        "display_name": "Child",
        "inherits": "generic.test",
        "chat": {"player_message_separators": ["|"]},
    }
    (generic / "profile.json").write_text(json.dumps(generic_payload), encoding="utf-8")
    (child / "profile.json").write_text(json.dumps(child_payload), encoding="utf-8")

    effective = ProfileRegistry(root).load_all()["child.test"]
    assert effective.chat.player_message_separators == ("|",)
    assert effective.chat.username_pattern == "^[A-Z][A-Za-z]{1,15}$"
    assert effective.chat.player_colors == ("#FFFFFF",)


def test_profile_regexes_reject_advanced_or_nested_constructs() -> None:
    bundled = ProfileRegistry(ROOT / "profiles").load_all()["generic.default"]
    payload = bundled.model_dump(mode="json")
    payload["chat"]["username_pattern"] = r"^(a+)+$"
    with pytest.raises(ValueError, match="regex quantifiers"):
        GameProfile.model_validate(payload)

    payload = bundled.model_dump(mode="json")
    payload["chat"]["username_pattern"] = r"^(?=admin).+$"
    with pytest.raises(ValueError, match="advanced regex constructs"):
        GameProfile.model_validate(payload)

    payload = bundled.model_dump(mode="json")
    payload["chat"]["username_pattern"] = r"^(?:a|aa)+$"
    with pytest.raises(ValueError, match="regex groups"):
        GameProfile.model_validate(payload)

    payload = bundled.model_dump(mode="json")
    payload["chat"]["username_pattern"] = r"^a*a*a*a*a*a*a*a*a*a*a*a*b$"
    with pytest.raises(ValueError, match="unbounded regex quantifiers"):
        GameProfile.model_validate(payload)

    payload = bundled.model_dump(mode="json")
    payload["chat"]["username_pattern"] = "^" + "a{1,256}" * 20 + "b$"
    with pytest.raises(ValueError, match="safe bound"):
        GameProfile.model_validate(payload)


def test_glossary_resource_id_rejects_path_traversal() -> None:
    bundled = ProfileRegistry(ROOT / "profiles").load_all()["generic.default"]
    payload = bundled.model_dump(mode="json")
    payload["resources"]["glossary_id"] = "../../outside"
    with pytest.raises(ValueError, match="simple resource identifier"):
        GameProfile.model_validate(payload)


def test_explicit_profile_announcement_opt_in_is_data_driven() -> None:
    override = ProfileOverride.model_validate(
        {
            "profile_id": "stalzone.default",
            "chat": {"announce_outbound": True, "announce_system": True},
        }
    )
    resources = ResourceRegistry(ROOT, overrides={override.profile_id: override}).load_all()[
        override.profile_id
    ]
    classifier = MessageClassifier(resources)
    outbound = classifier.classify(
        ChatLine(raw_text="-> Vasya: hi", normalized_text="", confidence=0.9, visual_order=0)
    )
    system = classifier.classify(
        ChatLine(
            raw_text="artifact event started",
            normalized_text="",
            confidence=0.9,
            visual_order=0,
        )
    )
    assert outbound.should_announce and system.should_announce
