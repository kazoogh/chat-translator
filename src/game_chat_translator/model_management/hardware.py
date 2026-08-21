from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any, ClassVar

from game_chat_translator.validation.schemas import ModelEntry


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    memory_bytes: int
    logical_cpus: int
    compatible_gpu: bool = False

    @property
    def recommended_tier(self) -> str:
        if self.compatible_gpu and self.memory_bytes >= 12 * 1024**3:
            return "gpu"
        if self.memory_bytes >= 8 * 1024**3 and self.logical_cpus >= 4:
            return "cpu_balanced"
        return "cpu_low"


def probe_hardware(*, compatible_gpu: bool = False) -> HardwareProfile:
    return HardwareProfile(_physical_memory(), os.cpu_count() or 1, compatible_gpu)


def recommend_model(
    entries: tuple[ModelEntry, ...],
    hardware: HardwareProfile,
    *,
    required_languages: frozenset[str] = frozenset({"ru", "tr", "en"}),
    override_model_id: str | None = None,
) -> ModelEntry | None:
    compatible = tuple(entry for entry in entries if required_languages.issubset(entry.languages))
    if override_model_id is not None:
        return next((item for item in compatible if item.model_id == override_model_id), None)
    tier_order = {"cpu_low": 0, "cpu_balanced": 1, "gpu": 2}
    maximum = tier_order[hardware.recommended_tier]
    eligible = tuple(item for item in compatible if tier_order[item.hardware_tier] <= maximum)
    return max(
        eligible,
        key=lambda item: (tier_order[item.hardware_tier], item.size_bytes),
        default=None,
    )


def _physical_memory() -> int:
    if os.name != "nt":
        try:
            sysconf = getattr(os, "sysconf", None)
            if sysconf is None:
                return 0
            page_size = sysconf("SC_PAGE_SIZE")
            pages = sysconf("SC_PHYS_PAGES")
            return int(page_size * pages)
        except (AttributeError, OSError, ValueError):
            return 0

    class MemoryStatus(ctypes.Structure):
        _fields_: ClassVar[list[tuple[str, Any]]] = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    windll = getattr(ctypes, "windll", None)
    if windll is None or not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.total_physical)
