from __future__ import annotations

import time
from threading import Thread

from game_chat_translator.reply.clipboard import ClipboardDispatchBridge


def test_successful_copy_runs_only_when_ui_owner_processes_request() -> None:
    bridge = ClipboardDispatchBridge()
    clipboard = ["sentinel"]
    outcomes: list[bool] = []
    worker = Thread(target=lambda: outcomes.append(bridge.request_copy("translated")))
    worker.start()
    deadline = time.monotonic() + 1
    while (
        worker.is_alive()
        and bridge.process(lambda text: clipboard.__setitem__(0, text) is None, maximum=1) == 0
    ):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.005)
    worker.join(timeout=1)
    assert outcomes == [True]
    assert clipboard == ["translated"]


def test_timed_out_request_can_never_overwrite_newer_clipboard_content() -> None:
    bridge = ClipboardDispatchBridge()
    clipboard = ["sentinel"]
    assert not bridge.request_copy("obsolete", timeout=0.01)
    clipboard[0] = "new user value"
    assert bridge.process(lambda text: clipboard.__setitem__(0, text) is None) == 0
    assert clipboard == ["new user value"]


def test_close_releases_waiter_without_copying() -> None:
    bridge = ClipboardDispatchBridge()
    outcomes: list[bool] = []
    worker = Thread(target=lambda: outcomes.append(bridge.request_copy("translated")))
    worker.start()
    time.sleep(0.01)
    bridge.close()
    bridge.close()
    worker.join(timeout=1)
    assert outcomes == [False]
