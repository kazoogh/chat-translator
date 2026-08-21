from __future__ import annotations

import json
from pathlib import Path

from game_chat_translator.model_management import HardwareProfile, recommend_model
from game_chat_translator.validation.schemas import ModelManifest

ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> ModelManifest:
    return ModelManifest.model_validate_json(
        (ROOT / "data" / "models" / "manifest.v1.json").read_text(encoding="utf-8")
    )


def test_hardware_tiers_recommend_best_compatible_manifest_entry() -> None:
    entries = _manifest().models
    assert recommend_model(entries, HardwareProfile(4 * 1024**3, 2)).hardware_tier == "cpu_low"  # type: ignore[union-attr]
    assert (
        recommend_model(entries, HardwareProfile(16 * 1024**3, 8)).hardware_tier  # type: ignore[union-attr]
        == "cpu_balanced"
    )
    assert (
        recommend_model(entries, HardwareProfile(16 * 1024**3, 8, True)).hardware_tier  # type: ignore[union-attr]
        == "gpu"
    )


def test_user_override_remains_explicit_and_manifest_is_license_complete() -> None:
    entries = _manifest().models
    selected = recommend_model(
        entries,
        HardwareProfile(4 * 1024**3, 2),
        override_model_id="qwen2.5-3b-instruct-q4-k-m",
    )
    assert selected is not None and selected.hardware_tier == "gpu"
    assert (
        recommend_model(entries, HardwareProfile(4 * 1024**3, 2), override_model_id="nope") is None
    )
    raw = json.loads((ROOT / "data" / "models" / "manifest.v1.json").read_text())
    assert all(item["license_id"] == "Apache-2.0" for item in raw["models"])
