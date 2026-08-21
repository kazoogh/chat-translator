from __future__ import annotations

from dataclasses import dataclass

from game_chat_translator.translation.base import TranslationRequest


@dataclass(frozen=True, slots=True)
class ContextMessage:
    speaker: str | None
    source_text: str
    translated_text: str | None = None


class TranslationRequestBuilder:
    def __init__(
        self,
        *,
        maximum_context_messages: int = 10,
        maximum_source_chars: int = 800,
        maximum_prompt_chars: int = 1_600,
        maximum_context_row_chars: int = 240,
    ) -> None:
        if not 3 <= maximum_context_messages <= 10:
            raise ValueError("translation context must contain between 3 and 10 messages")
        if (
            maximum_source_chars <= 0
            or maximum_prompt_chars < maximum_source_chars
            or maximum_context_row_chars <= 0
        ):
            raise ValueError("translation character bounds are invalid")
        self._maximum_context = maximum_context_messages
        self._maximum_source = maximum_source_chars
        self._maximum_prompt = maximum_prompt_chars
        self._maximum_context_row = maximum_context_row_chars

    def build(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str = "en",
        protected_terms: tuple[str, ...] = (),
        context: tuple[ContextMessage, ...] = (),
        context_generation: int,
        glossary_generation: int,
        model_generation: int,
    ) -> TranslationRequest:
        source = source_text
        if not source.strip():
            raise ValueError("translation source cannot be empty")
        if len(source) > self._maximum_source:
            raise ValueError("translation source exceeds the local model context budget")
        terms = _bounded_unique_terms(protected_terms, source)
        recent = context[-self._maximum_context :]
        protected = ", ".join(terms) if terms else "(none)"
        prefix = (
            "Translate the SOURCE into concise natural gamer "
            f"{target_language}. Preserve tone, profanity strength, names, numbers, emoticons, "
            "punctuation intensity, and every PROTECTED term exactly. "
            "Add no facts or explanations.\n"
            f"PROTECTED: {protected}\n"
        )
        suffix = f"SOURCE:\n{source}"
        empty_prompt = f"{prefix}CONTEXT:\n(none)\n{suffix}"
        if len(empty_prompt) > self._maximum_prompt:
            raise ValueError("source and protected terms exceed the local model context budget")
        selected: list[str] = []
        for item in reversed(recent):
            rendered = _render_context(item, self._maximum_context_row)
            proposal = [rendered, *selected]
            prompt = f"{prefix}CONTEXT:\n{chr(10).join(proposal)}\n{suffix}"
            if len(prompt) > self._maximum_prompt:
                break
            selected = proposal
        rendered_context = tuple(selected)
        prompt = (
            f"{prefix}CONTEXT:\n"
            f"{chr(10).join(rendered_context) if rendered_context else '(none)'}\n{suffix}"
        )
        return TranslationRequest(
            source_text=source,
            source_language=source_language,
            target_language=target_language,
            protected_terms=terms,
            context=rendered_context,
            prompt=prompt,
            context_generation=context_generation,
            glossary_generation=glossary_generation,
            model_generation=model_generation,
        )


def _bounded_unique_terms(terms: tuple[str, ...], source: str) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms[:128]:
        rendered = term[:200]
        key = rendered.casefold()
        if rendered and key not in seen and rendered.casefold() in source.casefold():
            unique.append(rendered)
            seen.add(key)
    return tuple(unique)


def _render_context(message: ContextMessage, maximum: int) -> str:
    speaker = (message.speaker or "unknown")[:80]
    source = message.source_text[:maximum].replace("\r", " ").replace("\n", " ")
    translated = (
        message.translated_text[:maximum].replace("\r", " ").replace("\n", " ")
        if message.translated_text
        else ""
    )
    return f"{speaker}: {source}" + (f" => {translated}" if translated else "")
