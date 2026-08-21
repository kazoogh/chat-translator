from __future__ import annotations

import json
from pathlib import Path

from game_chat_translator.classification.classifier import MessageClassifier
from game_chat_translator.classification.evaluation import (
    ClassificationFixture,
    evaluate,
    held_out,
)
from game_chat_translator.models import ChatLine, MessageClass, Point
from game_chat_translator.profiles.resources import ResourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def _classifier(profile_id: str = "stalzone.default") -> MessageClassifier:
    resources = ResourceRegistry(ROOT).load_all()[profile_id]
    return MessageClassifier(resources, own_username="LocalPlayer")


def _line(
    text: str,
    *,
    confidence: float = 0.95,
    left: float | None = None,
    colors: tuple[str, ...] = (),
) -> ChatLine:
    boxes = ()
    if left is not None:
        box = (
            Point(x=left, y=0),
            Point(x=left + 10, y=0),
            Point(x=left + 10, y=5),
            Point(x=left, y=5),
        )
        boxes = (box,)
    return ChatLine(
        raw_text=text,
        normalized_text=text,
        confidence=confidence,
        visual_order=0,
        boxes=boxes,
        colors=colors,
    )


def test_classifier_is_conservative_and_preserves_player_body() -> None:
    classifier = _classifier()
    inbound = classifier.classify(_line("Vasya: take [Ice Hedgehog]!!!"))
    assert inbound.message.classification is MessageClass.PLAYER_INBOUND
    assert inbound.message.speaker == "Vasya"
    assert inbound.message.body == "take [Ice Hedgehog]!!!"
    assert inbound.reason_code == "VALID_PLAYER_LAYOUT_ITEM_LINK"
    assert inbound.should_announce

    for text in ("-> Friend: hello", "LocalPlayer: hello"):
        outbound = classifier.classify(_line(text))
        assert outbound.message.classification is MessageClass.PLAYER_OUTBOUND
        assert not outbound.should_announce

    system = classifier.classify(_line("artifact event started"))
    assert system.message.classification is MessageClass.SYSTEM
    assert not system.should_announce

    unknown = classifier.classify(_line("artifact event almost started"))
    assert unknown.message.classification is MessageClass.UNKNOWN
    assert not unknown.should_announce


def test_low_confidence_and_username_near_miss_remain_visible_but_silent() -> None:
    classifier = _classifier()
    low = classifier.classify(_line("Vasya: hello", confidence=0.4))
    invalid = classifier.classify(_line("name with spaces: hello"))
    assert low.message.body == "Vasya: hello"
    assert low.message.classification is MessageClass.UNKNOWN
    assert invalid.message.classification is MessageClass.UNKNOWN
    assert not low.should_announce and not invalid.should_announce


def test_player_layout_wins_over_system_keywords_unless_system_color_is_reliable() -> None:
    classifier = _classifier()
    for text in (
        "Vasya: I left loot",
        "Trader: artifact found",
        "Scout: event started?",
    ):
        decision = classifier.classify(_line(text))
        assert decision.message.classification is MessageClass.PLAYER_INBOUND
        assert decision.should_announce

    colored = classifier.classify(_line("Vasya: artifact found", colors=("#F2D16B",)))
    assert colored.message.classification is MessageClass.SYSTEM
    assert not colored.should_announce


def test_wrapped_player_line_is_joined_only_with_visual_indentation() -> None:
    classifier = _classifier()
    decisions = classifier.classify_lines(
        (_line("Vasya: this is a wrapped", left=10), _line("message body", left=22))
    )
    assert len(decisions) == 1
    assert decisions[0].message.body == "this is a wrapped message body"
    assert decisions[0].should_announce


def test_same_core_classifier_switches_to_minecraft_profile_data() -> None:
    classifier = _classifier("minecraft.java")
    inbound = classifier.classify(_line("<Steve> hello"))
    system = classifier.classify(_line("Alex was slain by Zombie"))
    invalid = classifier.classify(_line("Name.With.Dot> hello"))
    assert inbound.message.classification is MessageClass.PLAYER_INBOUND
    assert system.message.classification is MessageClass.SYSTEM
    assert invalid.message.classification is MessageClass.UNKNOWN


def test_named_held_out_confusion_matrix_meets_quantitative_gate() -> None:
    payload = json.loads(
        (ROOT / "tests" / "fixtures" / "classification" / "stalzone_cases.json").read_text(
            encoding="utf-8"
        )
    )
    fixtures = [
        ClassificationFixture(
            fixture_id=case["id"],
            text=case["text"],
            expected=MessageClass(case["expected"]),
            confidence=case.get("confidence", 0.95),
        )
        for case in payload["cases"]
    ]
    for family in payload["families"]:
        fixtures.extend(
            ClassificationFixture(
                fixture_id=f"{family['id_prefix']}-{index:03d}",
                text=family["template"].format(n=index),
                expected=MessageClass(family["expected"]),
            )
            for index in range(family["count"])
        )
    evaluation = held_out(tuple(fixtures))
    assert evaluation == held_out(tuple(fixtures))
    metrics = evaluate(_classifier(), evaluation)
    assert metrics.inbound_total >= 20
    assert metrics.silent_total >= 50
    assert metrics.player_recall >= 0.95
    assert metrics.false_announcement_rate < 0.01
