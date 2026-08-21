from __future__ import annotations

from game_chat_translator.__main__ import main


def test_default_entrypoint_launches_the_desktop_shell(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "game_chat_translator.desktop.run_desktop_application",
        lambda: 17,
    )
    assert main([]) == 17
