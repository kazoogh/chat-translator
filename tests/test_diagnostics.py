from __future__ import annotations

import json

from game_chat_translator.diagnostics import collect_diagnostics


def test_diagnostics_are_redacted_and_json_serializable() -> None:
    diagnostics = collect_diagnostics()
    encoded = json.dumps(diagnostics)
    assert "privacy" in diagnostics
    assert "environment" not in encoded.casefold()
    foreground = diagnostics["foreground_window"]
    if foreground and "title" in foreground:
        assert foreground["title"] == "<redacted>"
