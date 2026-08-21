from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from game_chat_translator.validation.validators import validate_corpus


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    source: str
    expected_natural: str
    confidence: str
    meaning_markers: tuple[str, ...] = ()
    slang_markers: tuple[str, ...] = ()
    tone_markers: tuple[str, ...] = ()
    profanity_markers: tuple[str, ...] = ()
    protected_terms: tuple[str, ...] = ()
    forbidden_inventions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RubricScore:
    meaning: bool
    naturalness: bool
    slang: bool
    tone: bool
    profanity: bool
    protected_terms: bool
    no_invention: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.meaning,
                self.naturalness,
                self.slang,
                self.tone,
                self.profanity,
                self.protected_terms,
                self.no_invention,
            )
        )


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    high_confidence_total: int
    high_confidence_passed: int
    low_confidence_total: int
    low_confidence_passed: int
    scores: tuple[tuple[str, RubricScore], ...]

    @property
    def high_confidence_rate(self) -> float:
        return (
            self.high_confidence_passed / self.high_confidence_total
            if self.high_confidence_total
            else 0.0
        )


class Candidate(Protocol):
    def __call__(self, case: EvaluationCase) -> str: ...


def load_reviewed_corpus(path: Path) -> tuple[EvaluationCase, ...]:
    cases: list[EvaluationCase] = []
    for row in validate_corpus(path):
        expected = row.natural_english_meaning or row.natural_reply_translation
        if expected is None:
            raise ValueError("validated translation row has no expected output")
        direction = "meaning" if row.natural_english_meaning is not None else "reply"
        identity = hashlib.sha256(
            f"{direction}\0{row.source_text}\0{expected}".encode()
        ).hexdigest()[:24]
        annotations = (
            *row.protected_usernames_and_game_terms.usernames,
            *row.protected_usernames_and_game_terms.game_terms,
        )
        protected = tuple(
            term for term in annotations if term in row.source_text and term in expected
        )
        cases.append(
            EvaluationCase(
                case_id=f"stalzone-v1-{identity}",
                source=row.source_text,
                expected_natural=expected,
                confidence=(
                    "high"
                    if row.confidence_or_ambiguity_notes.strip().casefold() == "high"
                    else "low"
                ),
                protected_terms=protected,
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("reviewed translation corpus produced duplicate stable IDs")
    return tuple(cases)


def stable_held_out(
    cases: tuple[EvaluationCase, ...], *, bucket: int = 0
) -> tuple[EvaluationCase, ...]:
    if not 0 <= bucket < 5:
        raise ValueError("held-out bucket must be between zero and four")
    return tuple(
        case
        for case in cases
        if hashlib.sha256(case.case_id.encode("utf-8")).digest()[0] % 5 == bucket
    )


def evaluate(cases: tuple[EvaluationCase, ...], candidate: Candidate) -> EvaluationReport:
    rows: list[tuple[str, RubricScore]] = []
    high_total = high_passed = low_total = low_passed = 0
    for case in cases:
        output = candidate(case)
        folded = output.casefold()
        score = RubricScore(
            meaning=_contains_all(folded, case.meaning_markers),
            naturalness=_normalize(output) == _normalize(case.expected_natural),
            slang=_contains_all(folded, case.slang_markers),
            tone=_contains_all(folded, case.tone_markers),
            profanity=_contains_all(folded, case.profanity_markers),
            protected_terms=all(term in output for term in case.protected_terms),
            no_invention=not any(term.casefold() in folded for term in case.forbidden_inventions),
        )
        rows.append((case.case_id, score))
        if case.confidence == "high":
            high_total += 1
            high_passed += int(score.passed)
        else:
            low_total += 1
            low_passed += int(score.passed)
    return EvaluationReport(high_total, high_passed, low_total, low_passed, tuple(rows))


def _contains_all(output: str, markers: tuple[str, ...]) -> bool:
    return all(marker.casefold() in output for marker in markers)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())
