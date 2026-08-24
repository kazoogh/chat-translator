from __future__ import annotations

import os
import sys
from types import ModuleType

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _offline_modelscope(*_args: object, **_kwargs: object) -> object:
    raise RuntimeError("ModelScope access is disabled; use verified local models")


modelscope = ModuleType("modelscope")
modelscope.snapshot_download = _offline_modelscope  # type: ignore[attr-defined]
sys.modules["modelscope"] = modelscope


class _PcmOnlyAv(ModuleType):
    __gct_pcm_only__ = True

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError("PyAV decoding is disabled; reply audio must be in-memory PCM")


sys.modules["av"] = _PcmOnlyAv("av")

if os.name == "nt":
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kazoogh.GameChatTranslator")
    except (AttributeError, OSError):
        pass
