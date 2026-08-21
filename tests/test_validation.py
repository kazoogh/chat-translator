from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_chat_translator.profiles.loader import ProfileLoadError, ProfileRegistry
from game_chat_translator.validation.validators import (
    DataValidationError,
    validate_corpus,
    validate_glossary,
    validate_repository,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_repository_data_is_valid() -> None:
    validate_repository(ROOT)


def test_corpus_has_expected_reviewed_size() -> None:
    rows = validate_corpus(ROOT / "data" / "corpora" / "stalzone.translation.v1.jsonl")
    assert len(rows) == 211


def test_glossary_has_expected_reviewed_size() -> None:
    glossary = validate_glossary(ROOT / "data" / "glossaries" / "stalzone.v1.json")
    assert len(glossary.terms) == 77


def test_duplicate_alias_for_different_terms_is_rejected(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "glossary_id": "test.v1",
        "metadata": {"source": "synthetic", "notes": ""},
        "terms": [
            {"canonical_english": "One", "aliases": ["same"], "category": "test"},
            {"canonical_english": "Two", "aliases": ["SAME"], "category": "test"},
        ],
        "slang_and_profanity_notes": [],
    }
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataValidationError, match="duplicate glossary alias"):
        validate_glossary(path)


def test_profile_inheritance_cycle_is_rejected(tmp_path: Path) -> None:
    for profile_id, parent in (("test.one", "test.two"), ("test.two", "test.one")):
        directory = tmp_path / profile_id
        directory.mkdir()
        (directory / "profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": profile_id,
                    "version": 1,
                    "display_name": profile_id,
                    "inherits": parent,
                }
            ),
            encoding="utf-8",
        )
    with pytest.raises(ProfileLoadError, match="cycle"):
        ProfileRegistry(tmp_path).load_all()


def test_profile_resource_path_traversal_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "test.profile"
    directory.mkdir()
    (directory / "profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": "test.profile",
                "version": 1,
                "display_name": "Test",
                "resources": {"system_patterns": "../outside.json"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileLoadError, match="invalid profile"):
        ProfileRegistry(tmp_path).load_all()
