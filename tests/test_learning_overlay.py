from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from game_chat_translator.language.glossary import GlossaryLayer, GlossaryResolver
from game_chat_translator.learning import GlossaryLearner, InMemoryLearningRepository, Observation
from game_chat_translator.validation.validators import validate_glossary

ROOT = Path(__file__).resolve().parents[1]


def test_turkish_unicode_alias_survives_export_import_without_mutating_bundle() -> None:
    bundled_path = ROOT / "data" / "glossaries" / "stalzone.v1.json"
    before = hashlib.sha256(bundled_path.read_bytes()).hexdigest()
    bundled = validate_glossary(bundled_path)
    first = GlossaryLearner(
        InMemoryLearningRepository(), existing_canonical_terms={"Istanbul Cache"}
    )
    for index, speaker in enumerate(("ali", "ayşe", "mehmet"), start=1):
        first.observe(
            Observation(
                message_id=f"m{index}",
                speaker_id=speaker,
                observed_text="İstanbul önbelleği",
                proposed_canonical="Istanbul Cache",
                language="tr",
                confidence=0.98,
                ocr_stability=0.97,
                observed_at=datetime(2026, 8, 20, tzinfo=UTC),
            )
        )

    encoded = first.export_overlay().json_bytes()
    second = GlossaryLearner(InMemoryLearningRepository())
    imported = second.import_overlay(encoded)
    assert imported.terms[0].aliases == ("İstanbul önbelleği",)

    local = second.validated_local_glossary()
    match = GlossaryResolver(bundled, (), local).find("İSTANBUL ÖNBELLEĞİ ready")[-1]
    assert match.canonical_english == "Istanbul Cache"
    assert match.layer is GlossaryLayer.LOCAL
    assert hashlib.sha256(bundled_path.read_bytes()).hexdigest() == before


def test_local_overlay_takes_precedence_over_bundled_alias() -> None:
    bundled = validate_glossary(ROOT / "data" / "glossaries" / "stalzone.v1.json")
    alias = bundled.terms[0].aliases[0]
    learner = GlossaryLearner(InMemoryLearningRepository())
    payload = {
        "schema_version": 1,
        "glossary_id": "local.learned.v1",
        "terms": [
            {
                "canonical_english": "Local Override",
                "aliases": [alias],
                "category": "correction",
                "notes": "user confirmed",
            }
        ],
    }
    learner.import_overlay(payload)
    match = GlossaryResolver(bundled, (), learner.validated_local_glossary()).find(alias)[0]
    assert match.canonical_english == "Local Override"
    assert match.layer is GlossaryLayer.LOCAL
