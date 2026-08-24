from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

_SENSITIVE_KEY_PARTS = (
    "address",
    "audio",
    "chat",
    "clipboard",
    "device",
    "exception",
    "message",
    "path",
    "screenshot",
    "secret",
    "title",
    "token",
    "transcript",
    "username",
)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _memory_bytes() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_: ClassVar = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
    except (AttributeError, OSError):
        return None
    return None


def _foreground_window() -> dict[str, Any] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        if not handle:
            return None
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, class_buffer, len(class_buffer))
        rect = (ctypes.c_long * 4)()
        user32.GetClientRect(handle, rect)
        dpi = user32.GetDpiForWindow(handle) if hasattr(user32, "GetDpiForWindow") else 96
        return {
            "window_class": class_buffer.value,
            "title": "<redacted>",
            "client_width": max(0, int(rect[2] - rect[0])),
            "client_height": max(0, int(rect[3] - rect[1])),
            "dpi": int(dpi),
        }
    except (AttributeError, OSError):
        return {"error": "window metadata unavailable"}


def collect_diagnostics() -> dict[str, Any]:
    disk = shutil.disk_usage(Path.cwd().anchor)
    return {
        "schema_version": 1,
        "privacy": "window titles, usernames, paths, addresses, and device identifiers are omitted",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "hardware": {
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_bytes": _memory_bytes(),
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        },
        "foreground_window": _foreground_window(),
    }


def _redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 8:
        return "<redacted>"
    normalized_key = key.casefold()
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(child_key)[:80]: _redact(child_value, key=str(child_key), depth=depth + 1)
            for child_key, child_value in list(value.items())[:200]
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_redact(item, depth=depth + 1) for item in list(value)[:200]]
    if isinstance(value, str):
        redacted = value.replace(str(Path.home()), "<home>")
        redacted = _EMAIL.sub("<redacted>", redacted)
        return _IPV4.sub("<redacted>", redacted)[:512]
    if value is None or isinstance(value, bool | int | float):
        return value
    return "<redacted>"


def export_debug_bundle(output: Path, diagnostics: Mapping[str, Any] | None = None) -> None:
    """Write the strict, content-free support archive allowlist."""
    sanitized = _redact(diagnostics or collect_diagnostics())
    manifest = {
        "schema_version": 1,
        "files": ["diagnostics.json", "manifest.json"],
        "privacy": "No screenshots, chat, audio, transcripts, clipboard, logs, or settings.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(sanitized, indent=2, sort_keys=True) + "\n")
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a privacy-redacted hardware diagnostic")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bundle", action="store_true")
    args = parser.parse_args(argv)
    encoded = json.dumps(collect_diagnostics(), indent=2, sort_keys=True)
    if args.output:
        if args.bundle:
            export_debug_bundle(args.output)
        else:
            args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
