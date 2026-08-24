from __future__ import annotations

import json
import zipfile
from pathlib import Path

from game_chat_translator.diagnostics import collect_diagnostics, export_debug_bundle


def test_diagnostics_are_redacted_and_json_serializable() -> None:
    diagnostics = collect_diagnostics()
    encoded = json.dumps(diagnostics)
    assert "privacy" in diagnostics
    assert "environment" not in encoded.casefold()
    foreground = diagnostics["foreground_window"]
    if foreground and "title" in foreground:
        assert foreground["title"] == "<redacted>"


def test_debug_bundle_has_a_strict_allowlist_and_redacts_nested_canaries(
    tmp_path: Path,
) -> None:
    canary = "PRIVATE-CANARY-7f0c4a"
    output = tmp_path / "support.zip"
    export_debug_bundle(
        output,
        {
            "platform": {"system": "Windows"},
            "nested": {
                "exception": {"detail": canary},
                "path": f"C:\\Users\\private\\{canary}",
                "clipboard": canary,
                "transcript": canary,
            },
        },
    )
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "manifest.json"}
        encoded = b"".join(archive.read(name) for name in archive.namelist())
    assert canary.encode() not in encoded
    assert b"Windows" in encoded
