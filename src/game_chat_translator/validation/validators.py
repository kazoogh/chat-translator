from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from pydantic import ValidationError

from game_chat_translator.validation.schemas import CorpusRow, GlossaryFile, ModelManifest


class DataValidationError(RuntimeError):
    pass


MAX_DATA_BYTES = 16 * 1024 * 1024


def _read_json(path: Path) -> object:
    if path.stat().st_size > MAX_DATA_BYTES:
        raise DataValidationError(f"{path} exceeds the data size limit")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"invalid JSON in {path}") from exc


def validate_glossary(path: Path) -> GlossaryFile:
    try:
        glossary = GlossaryFile.model_validate(_read_json(path))
    except ValidationError as exc:
        raise DataValidationError(f"invalid glossary {path}: {exc}") from exc
    aliases: dict[str, str] = {}
    canonical_names: set[str] = set()
    for term in glossary.terms:
        canonical = unicodedata.normalize("NFKC", term.canonical_english).casefold()
        if canonical in canonical_names:
            raise DataValidationError(
                f"duplicate canonical glossary term: {term.canonical_english}"
            )
        canonical_names.add(canonical)
        for alias in term.aliases:
            key = unicodedata.normalize("NFKC", alias).casefold().strip()
            previous = aliases.get(key)
            if previous is not None and previous != term.canonical_english:
                raise DataValidationError(
                    f"duplicate glossary alias {alias!r} maps to both {previous!r} and "
                    f"{term.canonical_english!r}"
                )
            aliases[key] = term.canonical_english
    return glossary


def validate_corpus(path: Path) -> tuple[CorpusRow, ...]:
    if path.stat().st_size > MAX_DATA_BYTES:
        raise DataValidationError(f"{path} exceeds the data size limit")
    rows: list[CorpusRow] = []
    seen: set[tuple[str, str]] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = CorpusRow.model_validate_json(line)
                direction = "inbound" if row.natural_english_meaning is not None else "reply"
                key = (unicodedata.normalize("NFKC", row.source_text).casefold(), direction)
                if key in seen:
                    raise DataValidationError(f"duplicate corpus row at line {line_number}")
                seen.add(key)
                rows.append(row)
    except (OSError, UnicodeError, ValidationError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"invalid corpus {path}") from exc
    return tuple(rows)


def validate_model_manifest(path: Path) -> ModelManifest:
    try:
        manifest = ModelManifest.model_validate(_read_json(path))
    except ValidationError as exc:
        raise DataValidationError(f"invalid model manifest {path}: {exc}") from exc
    ids = [model.model_id for model in manifest.models]
    if len(ids) != len(set(ids)):
        raise DataValidationError("model manifest contains duplicate model IDs")
    return manifest


def validate_repository(root: Path) -> None:
    from game_chat_translator.profiles.resources import ResourceRegistry

    ResourceRegistry(root).load_all()
    validate_glossary(root / "data" / "glossaries" / "stalzone.v1.json")
    validate_corpus(root / "data" / "corpora" / "stalzone.translation.v1.jsonl")
    validate_model_manifest(root / "data" / "models" / "manifest.v1.json")
