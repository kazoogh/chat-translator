from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def bundled_resource_root() -> Path:
    """Return source-checkout or packaged immutable profile/data resources."""
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "data").is_dir() and (source_root / "profiles").is_dir():
        return source_root
    packaged = Path(str(files("game_chat_translator").joinpath("resources")))
    if not (packaged / "data").is_dir() or not (packaged / "profiles").is_dir():
        raise RuntimeError("bundled application resources are unavailable")
    return packaged
