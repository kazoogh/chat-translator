from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, ClassVar


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a privacy-redacted hardware diagnostic")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    encoded = json.dumps(collect_diagnostics(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
