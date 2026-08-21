from __future__ import annotations

from game_chat_translator.translation.prompting import ContextMessage, TranslationRequestBuilder


def test_request_builder_bounds_context_and_preserves_immutable_source_and_terms() -> None:
    source = "нужен Forge-11!!!"
    context = tuple(ContextMessage(f"p{index}", f"line {index}") for index in range(12))
    request = TranslationRequestBuilder(maximum_context_messages=3).build(
        source,
        source_language="ru",
        protected_terms=("Forge-11", "missing", "Forge-11"),
        context=context,
        context_generation=4,
        glossary_generation=5,
        model_generation=6,
    )
    assert request.source_text == source
    assert request.protected_terms == ("Forge-11",)
    assert request.context == ("p9: line 9", "p10: line 10", "p11: line 11")
    assert "Forge-11" in request.prompt
    assert request.context_generation == 4


def test_request_builder_rejects_empty_source() -> None:
    builder = TranslationRequestBuilder()
    try:
        builder.build(
            "  ",
            source_language="ru",
            context_generation=1,
            glossary_generation=1,
            model_generation=1,
        )
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty translation source was accepted")


def test_prompt_has_total_model_budget_and_evicts_oldest_context_first() -> None:
    source = "нужен Forge-11 сейчас"
    context = tuple(ContextMessage(f"p{index}", "x" * 8_000, "y" * 8_000) for index in range(10))
    request = TranslationRequestBuilder().build(
        source,
        source_language="ru",
        protected_terms=("Forge-11",),
        context=context,
        context_generation=1,
        glossary_generation=1,
        model_generation=1,
    )
    assert len(request.prompt) <= 1_600
    assert request.prompt.endswith(f"SOURCE:\n{source}")
    assert "Forge-11" in request.prompt
    assert request.context
    assert request.context[-1].startswith("p9:")
