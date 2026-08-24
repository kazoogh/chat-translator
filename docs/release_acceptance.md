# Release acceptance

## Automated evidence

- The accelerated 50,000-cycle soak exercises frame replacement, generational OCR backpressure, lossless UI messages with coalesced status, and exactly-once speech FIFO without wall-clock sleeps.
- Frozen release smoke loads Qt, PaddleOCR, OpenCV, CTranslate2/faster-whisper, llama.cpp, PortAudio, and PyAV, then starts a spawned child process from the windowed EXE.
- Installer smoke installs to a path containing spaces, launches with Python removed from `PATH`, repeats both frozen checks, and silently uninstalls while retaining user data by default.
- Debug-bundle tests inspect the ZIP allowlist and verify nested privacy canaries cannot enter the archive.

## Manual Windows checklist

Run on a clean Windows 11 x64 VM with no Python and on the target gaming PC. Record Windows build, CPU, GPU/driver, RAM, display topology/DPI, game build, profile version, OCR/STT/translation model revisions, capture interval, and sample count.

1. Install, decline startup and desktop shortcuts, launch, complete local model setup, calibrate, restart offline, remove/reinstall each model, upgrade, and uninstall once retaining and once explicitly removing user data.
2. For STALZONE and Minecraft, validate window detection, minimize/restore, rapid Alt-Tab, 16:9/ultrawide, mixed DPI, scroll deduplication, wrapped/item-link messages, outbound/system/unknown silence, and three consecutive inbound messages displayed and spoken exactly once.
3. Validate hold-to-talk down/up, accidental tap, lost focus, ambiguous target, translation/STT failure, clipboard failure, and shared `V` warning. Confirm every failed path preserves the seeded clipboard and no path focuses, pastes into, or sends input to the game.
4. Run at least four continuous hours of normal monitoring plus repeated pause/calibration/model-generation changes. Record peak working set, handle/thread counts, database/log growth, and any queue warnings before and after.
5. Measure p95 from visible chat line to translation, focus-change recovery, and key-release to copied reply. The architecture targets (<2 seconds translation/focus and <3 seconds reply) are not accepted until the named-hardware report and privacy-reviewed fixtures are attached.
6. Inspect the installed tree and installer archive for screenshots, usernames, chat/transcripts, recordings, model weights, test fixtures, unexpected executables, and missing license notices. Verify the published SHA-256 against the downloaded installer.

Hosted CI does not prove physical tray availability, audio playback, microphone quality, game compatibility, multi-monitor placement, or publisher anti-cheat approval. These remain explicit manual acceptance items and must not be represented as measured until the checklist evidence exists.
