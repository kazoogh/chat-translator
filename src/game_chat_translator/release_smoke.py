from __future__ import annotations

import importlib
import multiprocessing
import os
import sys
from multiprocessing.connection import Connection
from pathlib import Path


def _mark(stage: str) -> None:
    report = os.environ.get("GCT_SMOKE_REPORT")
    if report:
        with Path(report).open("a", encoding="utf-8") as stream:
            stream.write(f"{stage}\n")


def _frozen_child(connection: Connection) -> None:
    try:
        from game_chat_translator.resource_paths import bundled_resource_root

        connection.send(("ready", bundled_resource_root().is_dir()))
    finally:
        connection.close()


def run_frozen_runtime_smoke() -> None:
    """Load packaged native boundaries and prove frozen spawn bootstrap works."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _mark("start")

    av = importlib.import_module("av")

    if getattr(sys, "frozen", False) and not getattr(av, "__gct_pcm_only__", False):
        raise RuntimeError("the frozen runtime included the unsupported PyAV codec stack")

    _mark("av")
    importlib.import_module("ctranslate2")

    _mark("ctranslate2")
    import cv2  # noqa: F401

    _mark("cv2")
    import faster_whisper  # noqa: F401

    _mark("faster_whisper")
    import llama_cpp  # noqa: F401

    _mark("llama_cpp")
    import sounddevice  # noqa: F401

    _mark("sounddevice")
    from PySide6 import QtWidgets

    from game_chat_translator.vision.paddle_ocr import load_paddle_ocr_runtime

    load_paddle_ocr_runtime()
    _mark("paddleocr")
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    application.processEvents()
    _mark("qt")

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=_frozen_child, args=(child,), name="release-smoke")
    process.start()
    _mark("spawned")
    child.close()
    try:
        if not parent.poll(20.0):
            raise RuntimeError("frozen child process did not become ready")
        if parent.recv() != ("ready", True):
            raise RuntimeError("frozen child process returned an invalid result")
        process.join(timeout=10.0)
        if process.exitcode != 0:
            raise RuntimeError("frozen child process failed")
        _mark("complete")
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
