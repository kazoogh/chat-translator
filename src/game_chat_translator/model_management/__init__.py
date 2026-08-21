"""Secure, explicit lifecycle management for downloadable local models."""

from game_chat_translator.model_management.hardware import (
    HardwareProfile,
    probe_hardware,
    recommend_model,
)
from game_chat_translator.model_management.lifecycle import (
    DownloadCommand,
    DownloadResponse,
    InstalledModelRecord,
    ModelLifecycleManager,
    ModelOutcome,
    ModelOutcomeStatus,
    ModelSource,
    ModelStateStore,
)
from game_chat_translator.model_management.urllib_source import UrllibModelSource

__all__ = [
    "DownloadCommand",
    "DownloadResponse",
    "HardwareProfile",
    "InstalledModelRecord",
    "ModelLifecycleManager",
    "ModelOutcome",
    "ModelOutcomeStatus",
    "ModelSource",
    "ModelStateStore",
    "UrllibModelSource",
    "probe_hardware",
    "recommend_model",
]
