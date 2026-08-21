from __future__ import annotations

import re
from dataclasses import dataclass, replace
from uuid import UUID

from game_chat_translator.models import ChatLine, ClassifiedMessage, MessageClass
from game_chat_translator.profiles.resources import ProfileResources


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    message: ClassifiedMessage
    should_announce: bool
    reason_code: str
    source_visual_order: int = 0
    source_line_ids: tuple[UUID, ...] = ()


class MessageClassifier:
    def __init__(
        self,
        resources: ProfileResources,
        *,
        own_username: str | None = None,
        minimum_confidence: float = 0.65,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("classification confidence must be between zero and one")
        self._resources = resources
        self._chat = resources.profile.chat
        self._username = re.compile(self._chat.username_pattern)
        self._item_links = tuple(re.compile(pattern) for pattern in self._chat.item_link_patterns)
        self._own_username = own_username.casefold() if own_username else None
        self._minimum_confidence = minimum_confidence

    def classify(self, line: ChatLine) -> ClassificationDecision:
        decision = self._classify(line)
        return replace(
            decision,
            source_visual_order=line.visual_order,
            source_line_ids=(line.line_id,),
        )

    def _classify(self, line: ChatLine) -> ClassificationDecision:
        raw = line.raw_text[:8_192].strip()
        if line.confidence < self._minimum_confidence or not raw:
            return self._unknown(raw, line.confidence, "LOW_OCR_CONFIDENCE")

        outgoing = self._strip_outgoing_marker(raw)
        if outgoing is not None:
            speaker, body = self._parse_player(outgoing)
            return self._decision(
                MessageClass.PLAYER_OUTBOUND,
                body or outgoing,
                speaker,
                0.98,
                "OUTGOING_DIRECTION_MARKER",
            )

        colors = {color.upper() for color in line.colors}
        system_color = bool(colors & set(self._chat.system_colors))
        player_color = bool(colors & set(self._chat.player_colors))
        if system_color and not player_color:
            return self._decision(MessageClass.SYSTEM, raw, None, 0.96, "SYSTEM_COLOR")

        speaker, body = self._parse_player(raw)
        if speaker is not None and body:
            if self._own_username is not None and speaker.casefold() == self._own_username:
                return self._decision(
                    MessageClass.PLAYER_OUTBOUND,
                    body,
                    speaker,
                    0.99,
                    "OWN_USERNAME",
                )
            reason = (
                "VALID_PLAYER_LAYOUT_ITEM_LINK"
                if any(pattern.search(body) for pattern in self._item_links)
                else "VALID_PLAYER_LAYOUT"
            )
            return self._decision(
                MessageClass.PLAYER_INBOUND,
                body,
                speaker,
                min(0.99, line.confidence),
                reason,
            )

        if self._resources.matches_system(raw):
            return self._decision(MessageClass.SYSTEM, raw, None, 0.99, "KNOWN_SYSTEM_PATTERN")
        if colors & set(self._chat.outgoing_colors):
            return self._decision(MessageClass.PLAYER_OUTBOUND, raw, None, 0.8, "OUTGOING_COLOR")
        return self._unknown(raw, min(line.confidence, 0.6), "UNRECOGNIZED_LAYOUT")

    def classify_lines(self, lines: tuple[ChatLine, ...]) -> tuple[ClassificationDecision, ...]:
        decisions: list[ClassificationDecision] = []
        previous_line: ChatLine | None = None
        for line in lines:
            decision = self.classify(line)
            if (
                decision.message.classification is MessageClass.UNKNOWN
                and decisions
                and previous_line is not None
                and self._is_wrapped_continuation(previous_line, line)
                and decisions[-1].message.classification
                in {MessageClass.PLAYER_INBOUND, MessageClass.PLAYER_OUTBOUND}
            ):
                prior = decisions[-1]
                merged = prior.message.model_copy(
                    update={
                        "body": f"{prior.message.body} {line.raw_text.strip()}",
                        "confidence": min(prior.message.confidence, line.confidence),
                    }
                )
                decisions[-1] = replace(
                    prior,
                    message=merged,
                    reason_code="WRAPPED_PLAYER_CONTINUATION",
                    source_line_ids=(*prior.source_line_ids, line.line_id),
                )
            else:
                decisions.append(decision)
            previous_line = line
        return tuple(decisions)

    def _strip_outgoing_marker(self, text: str) -> str | None:
        for marker in sorted(self._chat.direction_markers, key=len, reverse=True):
            if text.startswith(marker) and (
                len(text) == len(marker) or text[len(marker)].isspace()
            ):
                return text[len(marker) :].strip()
        return None

    def _parse_player(self, text: str) -> tuple[str | None, str]:
        for separator in sorted(self._chat.player_message_separators, key=len, reverse=True):
            index = text.find(separator)
            if index <= 0:
                continue
            candidate = text[:index].strip().removeprefix("<").removesuffix(">")
            body = text[index + len(separator) :].strip()
            if len(candidate) <= 80 and self._username.fullmatch(candidate) and body:
                return candidate, body
        return None, text

    @staticmethod
    def _is_wrapped_continuation(previous: ChatLine, current: ChatLine) -> bool:
        if not previous.boxes or not current.boxes:
            return False
        previous_left = min(point.x for box in previous.boxes for point in box)
        current_left = min(point.x for box in current.boxes for point in box)
        return current_left >= previous_left + 8

    def _decision(
        self,
        classification: MessageClass,
        body: str,
        speaker: str | None,
        confidence: float,
        reason: str,
    ) -> ClassificationDecision:
        message = ClassifiedMessage(
            classification=classification,
            speaker=speaker,
            body=body,
            confidence=confidence,
        )
        announce = (
            classification is MessageClass.PLAYER_INBOUND
            or (classification is MessageClass.PLAYER_OUTBOUND and self._chat.announce_outbound)
            or (classification is MessageClass.SYSTEM and self._chat.announce_system)
        )
        return ClassificationDecision(message, announce, reason)

    def _unknown(self, body: str, confidence: float, reason: str) -> ClassificationDecision:
        return self._decision(MessageClass.UNKNOWN, body, None, confidence, reason)
