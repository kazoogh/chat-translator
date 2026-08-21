from __future__ import annotations

from pathlib import Path

from game_chat_translator.translation.evaluation import (
    EvaluationCase,
    evaluate,
    load_reviewed_corpus,
    stable_held_out,
)

ROOT = Path(__file__).resolve().parents[1]


def _cases() -> tuple[EvaluationCase, ...]:
    return (
        EvaluationCase(
            "high-meaning-tone",
            "source",
            "damn, meet at Forge-11!",
            "high",
            meaning_markers=("meet",),
            tone_markers=("!",),
            profanity_markers=("damn",),
            protected_terms=("Forge-11",),
            forbidden_inventions=("tomorrow",),
        ),
        EvaluationCase(
            "low-ambiguous",
            "source",
            "maybe scanner",
            "low",
            meaning_markers=("scanner",),
        ),
        EvaluationCase("high-slang", "source", "what's up?", "high", slang_markers=("what's up",)),
        EvaluationCase(
            "high-invention", "source", "go now", "high", forbidden_inventions=("loot",)
        ),
        EvaluationCase("heldout-padding-1", "s", "one", "high"),
        EvaluationCase("heldout-padding-2", "s", "two", "high"),
    )


def test_evaluator_reports_separate_rubric_dimensions_and_confidence_denominators() -> None:
    cases = _cases()[:4]
    outputs = {case.case_id: case.expected_natural for case in cases}
    outputs["high-invention"] = "go now with loot"
    report = evaluate(cases, lambda case: outputs[case.case_id])
    assert report.high_confidence_total == 3
    assert report.high_confidence_passed == 2
    assert report.low_confidence_total == 1
    assert report.low_confidence_passed == 1
    invention = dict(report.scores)["high-invention"]
    assert invention.naturalness is False
    assert invention.no_invention is False
    assert report.high_confidence_rate == 2 / 3


def test_held_out_split_is_stable_and_does_not_depend_on_input_order() -> None:
    cases = _cases()
    selected = stable_held_out(cases, bucket=0)
    reversed_selected = stable_held_out(tuple(reversed(cases)), bucket=0)
    assert {case.case_id for case in selected} == {case.case_id for case in reversed_selected}


def test_real_reviewed_corpus_has_stable_heldout_denominators() -> None:
    cases = load_reviewed_corpus(ROOT / "data" / "corpora" / "stalzone.translation.v1.jsonl")
    assert len(cases) == 211
    assert len({case.case_id for case in cases}) == 211
    assert sum(case.confidence == "high" for case in cases) == 192
    heldout = stable_held_out(cases)
    assert heldout
    assert all(case in cases for case in heldout)
