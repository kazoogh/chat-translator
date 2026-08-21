from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from game_chat_translator.validation.schemas import GlossaryFile


class GlossaryLayer(StrEnum):
    BUNDLED = "bundled"
    COMMUNITY = "community"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class GlossaryMatch:
    start: int
    end: int
    source: str
    canonical_english: str
    layer: GlossaryLayer


@dataclass(frozen=True, slots=True)
class _Alias:
    normalized: str
    canonical: str
    layer: GlossaryLayer


class GlossaryResolver:
    def __init__(
        self,
        bundled: GlossaryFile | None,
        community: tuple[GlossaryFile, ...] = (),
        local: GlossaryFile | None = None,
    ) -> None:
        aliases: dict[str, _Alias] = {}
        layers: list[tuple[GlossaryLayer, GlossaryFile]] = []
        if bundled is not None:
            layers.append((GlossaryLayer.BUNDLED, bundled))
        layers.extend((GlossaryLayer.COMMUNITY, glossary) for glossary in community)
        if local is not None:
            layers.append((GlossaryLayer.LOCAL, local))
        for layer, glossary in layers:
            for term in glossary.terms:
                for source in (*term.aliases, term.canonical_english):
                    normalized = _normalize(source)
                    aliases[normalized] = _Alias(normalized, term.canonical_english, layer)
        self._aliases = tuple(
            sorted(aliases.values(), key=lambda item: len(item.normalized), reverse=True)
        )

    def find(self, text: str) -> tuple[GlossaryMatch, ...]:
        normalized, positions = _normalized_with_positions(text)
        occupied: list[tuple[int, int]] = []
        matches: list[GlossaryMatch] = []
        for alias in self._aliases:
            for found in re.finditer(re.escape(alias.normalized), normalized):
                if not _word_boundary(normalized, found.start(), found.end()):
                    continue
                start = positions[found.start()][0]
                end = positions[found.end() - 1][1]
                if any(start < used_end and end > used_start for used_start, used_end in occupied):
                    continue
                occupied.append((start, end))
                matches.append(
                    GlossaryMatch(start, end, text[start:end], alias.canonical, alias.layer)
                )
        return tuple(sorted(matches, key=lambda item: item.start))

    def protected_terms(self, text: str) -> tuple[str, ...]:
        return tuple(match.source for match in self.find(text))


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _normalized_with_positions(text: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    output: list[str] = []
    positions: list[tuple[int, int]] = []
    pending_space = False
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        folded = unicodedata.normalize("NFKC", text[index:end]).casefold()
        for rendered in folded:
            if rendered.isspace():
                pending_space = bool(output)
                continue
            if pending_space:
                output.append(" ")
                positions.append((index, end))
                pending_space = False
            output.append(rendered)
            positions.append((index, end))
        index = end
    return "".join(output), tuple(positions)


def _word_boundary(text: str, start: int, end: int) -> bool:
    left_ok = start == 0 or not text[start - 1].isalnum()
    right_ok = end == len(text) or not text[end].isalnum()
    return left_ok and right_ok
