from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_fixture_helper_rejects_path_traversal_identifier(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    image.write_bytes(b"not decoded by the annotation helper")
    script = Path(__file__).resolve().parents[1] / "scripts" / "capture_fixture.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(image),
            "--fixture-id",
            "../escape",
            "--source-text",
            "synthetic",
            "--language",
            "en",
            "--confirm-private-content",
            "--output-dir",
            str(tmp_path / "fixtures"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "fixture ID" in result.stderr
    assert not (tmp_path / "escape.png").exists()
