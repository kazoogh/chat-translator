from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "game_chat_translator"

FORBIDDEN_IMPORTS = {
    "pymem",
    "frida",
    "scapy",
    "pyautogui",
    "keyboard",
    "sentry_sdk",
    "openai",
}
FORBIDDEN_CALL_NAMES = {
    "ReadProcessMemory",
    "WriteProcessMemory",
    "CreateRemoteThread",
    "SendInput",
    "keybd_event",
    "mouse_event",
}


def test_source_has_no_forbidden_imports_or_calls() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                if names & FORBIDDEN_IMPORTS:
                    violations.append(f"{path}: forbidden import {names & FORBIDDEN_IMPORTS}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                name = node.module.split(".")[0]
                if name in FORBIDDEN_IMPORTS:
                    violations.append(f"{path}: forbidden import {name}")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALL_NAMES:
                violations.append(f"{path}: forbidden call {node.attr}")
    assert violations == []


def test_base_imports_do_not_require_heavy_providers() -> None:
    import game_chat_translator.events
    import game_chat_translator.models
    import game_chat_translator.settings
    import game_chat_translator.storage.database  # noqa: F401
