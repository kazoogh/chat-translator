from __future__ import annotations

from uuid import uuid4

import pytest

from game_chat_translator.ui.single_instance import SingleInstanceGuard

pytestmark = pytest.mark.windows_ui


def test_second_desktop_instance_activates_the_existing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    activations: list[str] = []
    name = f"gct-test-{uuid4()}"
    first = SingleInstanceGuard(name, lambda: activations.append("show"))
    assert first.is_primary
    second = SingleInstanceGuard(name, lambda: None)
    assert not second.is_primary
    for _ in range(5):
        application.processEvents()
    assert activations == ["show"]
    second.close()
    first.close()
