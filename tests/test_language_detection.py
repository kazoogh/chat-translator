from __future__ import annotations

from pathlib import Path

import pytest

from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.language.glossary import GlossaryLayer, GlossaryResolver
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.validation.schemas import GlossaryFile

ROOT = Path(__file__).resolve().parents[1]


def _glossary(glossary_id: str, canonical: str, alias: str) -> GlossaryFile:
    return GlossaryFile.model_validate(
        {
            "schema_version": 1,
            "glossary_id": glossary_id,
            "metadata": {"source": "synthetic unit test"},
            "terms": [
                {
                    "canonical_english": canonical,
                    "aliases": [alias],
                    "category": "test",
                }
            ],
        }
    )


def test_detects_russian_english_turkish_and_transliteration() -> None:
    detector = LocalLanguageDetector()
    assert detector.analyze("привет куда идёшь").primary_language == "ru"
    assert detector.analyze("hello where are you").primary_language == "en"
    assert detector.analyze("mahmut naber kanka").primary_language == "tr"
    assert detector.analyze("privet brat").primary_language == "ru-Latn"


def test_mixed_script_analysis_preserves_names_numbers_emoticons_and_terms() -> None:
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    detector = LocalLanguageDetector(GlossaryResolver(resources.glossary))
    analysis = detector.analyze("Vasya привет abi, need 3 Elbrus XD")
    languages = {span.language for span in analysis.spans}
    assert analysis.primary_language == "mixed"
    assert {"ru", "tr", "en", "protected"} <= languages
    assert analysis.protected_terms == ("Elbrus", "XD")


def test_ambiguous_latin_name_does_not_gain_false_language_confidence() -> None:
    analysis = LocalLanguageDetector().analyze(
        "Zyphor42 XD 123", additional_protected_terms=("Zyphor42", "XD")
    )
    assert analysis.primary_language == "unknown"
    assert analysis.confidence == 0.0
    assert analysis.protected_terms == ("Zyphor42", "XD")


def test_glossary_longest_match_and_layer_precedence_are_deterministic() -> None:
    bundled = _glossary("bundled.test", "Bundled Elbrus", "Elbrus")
    community = _glossary("community.test", "Community Elbrus", "Elbrus")
    local = _glossary("local.test", "Local Elbrus", "Elbrus")
    resolver = GlossaryResolver(bundled, (community,), local)
    match = resolver.find("need Elbrus now")[0]
    assert match.canonical_english == "Local Elbrus"
    assert match.layer is GlossaryLayer.LOCAL


def test_turkish_unicode_alias_survives_normalization() -> None:
    glossary = _glossary("turkish.test", "Istanbul", "İstanbul")
    match = GlossaryResolver(glossary).find("i\u0307stanbul trade")[0]
    assert match.source == "i\u0307stanbul"
    assert match.canonical_english == "Istanbul"


def test_blank_glossary_alias_is_rejected_before_matching() -> None:
    with pytest.raises(ValueError, match="visible characters"):
        _glossary("invalid.test", "Term", "   ")


def test_statistical_provider_never_receives_protected_terms() -> None:
    received: list[str] = []

    class Provider:
        def predict(self, text: str) -> tuple[str, float]:
            received.append(text)
            return "en", 0.9

        def close(self) -> None:
            return None

    glossary = _glossary("protected.test", "Mount Elbrus", "Elbrus")
    detector = LocalLanguageDetector(GlossaryResolver(glossary), Provider())
    text = "attack Elbrus base now"
    analysis = detector.analyze(text, additional_protected_terms=("now",))
    assert received == ["attack base"]
    assert analysis.primary_language == "en"
    english_spans = [span for span in analysis.spans if span.language == "en"]
    assert [text[span.start : span.end] for span in english_spans] == ["attack", "base"]
