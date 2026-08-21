from __future__ import annotations

import socket
from pathlib import Path

from game_chat_translator.classification.classifier import MessageClassifier
from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.language.glossary import GlossaryResolver
from game_chat_translator.models import ChatLine, MessageClass
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.storage.database import Database
from game_chat_translator.translation import TranslationRequestBuilder, TranslationRouter
from game_chat_translator.translation.base import CancellationToken, TranslationRequest

ROOT = Path(__file__).resolve().parents[1]


class _OfflineProvider:
    provider_id = "local-test"
    model_id = "fixture-v1"

    def health_check(self) -> bool:
        return True

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        del timeout_seconds, cancellation
        assert request.source_language == "ru"
        return "where are you going to Forge-11?"

    def close(self) -> None:
        pass


def test_classify_detect_translate_path_works_with_network_denied_and_no_history(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    def denied(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("normal translation attempted outbound networking")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    decision = MessageClassifier(resources).classify(
        ChatLine(
            raw_text="Vasya: ты куда идёшь в Forge-11?",
            normalized_text="Vasya: ты куда идёшь в Forge-11?",
            confidence=0.98,
            visual_order=0,
        )
    )
    assert decision.message.classification is MessageClass.PLAYER_INBOUND
    glossary = GlossaryResolver(resources.glossary)
    analysis = LocalLanguageDetector(glossary).analyze(decision.message.body)
    request = TranslationRequestBuilder().build(
        decision.message.body,
        source_language=analysis.primary_language,
        protected_terms=analysis.protected_terms,
        context_generation=1,
        glossary_generation=1,
        model_generation=1,
    )
    outcome = TranslationRouter(_OfflineProvider(), None).translate(request)
    assert outcome.result.natural_text == "where are you going to Forge-11?"
    assert not outcome.degraded

    with Database(tmp_path / "state.sqlite3") as database:
        assert database.open().execute("SELECT COUNT(*) FROM message_history").fetchone()[0] == 0
