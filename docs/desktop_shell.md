# desktop shell and inbound speech

Slice 5 adds the tray-first PySide6 shell and the ordered Windows SAPI boundary.

Run the desktop development build on Windows with Python 3.12:

```powershell
python -m uv run --extra ui --extra windows --extra capture --extra vision --extra language --extra translation game-chat-translator
```

The dashboard contains Status, Capture, Profiles, Translation Models, Audio & Voice, Hotkeys,
History, and Diagnostics pages. Closing the dashboard hides it when the Windows tray is available;
only explicit Quit or Windows session shutdown closes workers and storage. If the tray is unavailable,
closing the dashboard routes through explicit Quit so the process cannot become invisible.

The speech provider is constructed and used only on its dedicated COM-initialized worker thread.
Inbound player translations enter a bounded FIFO through a separate nonblocking presentation
backlog, so speech pressure cannot stall capture/OCR and accepted messages remain ordered. Outbound,
system, and unknown messages remain visual and are rejected before speech admission. Muting cancels current
speech, purges queued speech, and rejects new announcements until unmuted. SAPI receives plain text
with the non-XML flag. Provider failure never removes the visual translation.

History remains memory-only by default. Enabling persistence requires a retention period from 1 to
365 days, stores only the bounded documented fields with an expiry, purges expired/over-limit rows,
and never enables diagnostic text logging. Clear History removes UI messages, translation context
and cache, pending writes, and persisted message history without deleting calibrations or learned
terms.

Model downloads occur only after pressing a model's Download / Verify button and retain the Slice 4
allowlist, size, digest, license, cancellation, and activation checks. Opening the model page performs
no network request. The PaddleOCR setup entry downloads only eight files from two fixed upstream
revisions, verifies every size and SHA-256, and activates both detection and Cyrillic-recognition
directories as one atomic bundle. Live monitoring remains in setup state until both OCR models and a
calibrated chat region are available. Global hotkey registration and hold-to-talk audio are implemented in Slice 6;
Slice 5 displays their configured values but does not observe or suppress keys.

See [`slice5_manual_test_checklist.md`](slice5_manual_test_checklist.md) for physical Windows checks.
