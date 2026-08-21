from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from game_chat_translator.events import DomainEvent, EventName
from game_chat_translator.models import ChatRegion


def test_chat_region_must_be_normalized_and_contained() -> None:
    region = ChatRegion(
        x=0.1,
        y=0.7,
        width=0.5,
        height=0.2,
        layout_id="default",
        reference_client_width=1920,
        reference_client_height=1080,
        reference_dpi=144,
    )
    assert region.x + region.width <= 1
    with pytest.raises(ValidationError, match="contained"):
        region.model_copy(update={"x": 0.8, "width": 0.3}).model_validate(
            {**region.model_dump(), "x": 0.8, "width": 0.3}
        )


def test_domain_events_require_utc_and_are_frozen() -> None:
    event = DomainEvent(
        session_id=uuid4(),
        created_at=datetime.now(UTC),
        name=EventName.FRAME_CAPTURED,
    )
    with pytest.raises(ValidationError):
        event.name = EventName.OCR_COMPLETED  # type: ignore[misc]
    with pytest.raises(ValidationError, match="UTC"):
        DomainEvent(
            session_id=uuid4(),
            created_at=datetime.now(UTC).astimezone(timezone(timedelta(hours=1))),
            name=EventName.FRAME_CAPTURED,
        )
