# build plan

status: ready to execute  
target: Windows 10/11 x64  
delivery strategy: small vertical pull requests with tests and runnable checkpoints

implementation status: slice 0 completed on 2026-08-20; slices 1–7 remain in progress. The slice-0
gate passes on the local Windows Python 3.13 environment and is configured for Python 3.12 on
Windows/Linux CI.

## execution rules

- keep `main` releasable; build on scoped branches and merge only validated slices.
- define domain contracts before provider integrations.
- use dependency injection so tests run without a GPU, microphone, active game, or downloaded model.
- keep optional heavy dependencies in extras; the base test environment must stay lightweight.
- pin dependencies in `uv.lock`; build Windows artifacts on Windows runners.
- add fixtures before tuning thresholds; never tune exclusively against the held-out corpus partition.
- every slice updates tests, documentation, and migration/schema versions together.
- never add game memory access, injection, automatic input, telemetry, or a paid core provider.

## slice 0 — repository foundation

deliver:

- `pyproject.toml`, package scaffold, `uv.lock`, Ruff, mypy, pytest, and pre-commit configuration.
- typed domain models/events from `docs/runtime_contracts.md`.
- versioned settings loader with atomic backup/recovery.
- SQLite connection, migration runner, repository interfaces, and initial schema.
- validators for profile, glossary, corpus, and model-manifest data.
- `generic.default`, `stalzone.default`, and `minecraft.java` profile skeletons.
- Windows/Linux CI for portable tests; Windows packaging smoke job placeholder.
- PowerShell bootstrap and hardware/window-metadata diagnostic commands.

gate:

- clean clone runs one bootstrap command and all portable tests pass.
- malformed configuration/data fails with actionable errors.
- migrations are repeatable and rollback is not required for ordinary startup recovery.
- no runtime module imports an unavailable heavy provider during base tests.

## slice 1 — capture, game detection, and calibration

deliver:

- Win32 foreground-window metadata provider.
- profile matcher with confidence, debounce, manual override, and unknown-game fallback.
- `dxcam` capture with `mss` fallback.
- frozen-screenshot clipping UI with drag, move, resize, nudge, preview, reset, retry, cancel, and save.
- normalized client-relative calibration persistence and DPI/multi-monitor conversion.

gate:

- synthetic-window tests cover focus changes, resize, movement, minimization, DPI, and multiple monitors.
- capture is restricted to the calibrated region and stops when paused/minimized.
- no injection, game hook, memory read, or simulated input exists in dependencies or code paths.

## slice 2 — OCR and line tracking

deliver:

- PaddleOCR 3.x adapter behind the OCR interface.
- CPU model setup and optional compatible GPU provider selected by health check.
- profile-driven preprocessing and diagnostic crop/bounding-box preview.
- line grouping, normalization, scrolling alignment, duplicate suppression, and expiry.
- fixture capture/annotation helper.

gate:

- static sequences emit no duplicates and later legitimate repeated messages reappear.
- held-out STALZONE OCR/player-message recall reaches the architecture target or failures are documented by fixture.
- provider failure degrades visibly without killing the tray process.

## slice 3 — classification, profiles, and language data

deliver:

- inbound/outbound/system/unknown classifier.
- validated resource registry and glossary precedence.
- STALZONE chat colors, separators, system patterns, and item-link handling.
- Minecraft Java default-chat rules plus manual calibration for custom scale/layout.
- language identification and mixed-script analysis for Russian, English, and Turkish.

gate:

- system and outbound false announcements remain below the target rate.
- unknown lines are visible but silent.
- switching STALZONE/Minecraft changes only profile data, not core-engine code.

## slice 4 — local translation and live learning

deliver:

- contextual translator interface and bounded prompt/context builder.
- bundled `llama.cpp`-compatible runtime adapter plus lightweight Argos fallback.
- allowlisted model manifest, hardware tiers, checksummed download, cancellation, and atomic activation.
- natural-gamer translation policy and corpus evaluator.
- local glossary candidate collection, evidence scoring, conflict checks, activation, rejection suppression, and import/export.

gate:

- normal translation works with outbound networking blocked after model setup.
- corpus quality reaches the architecture target without inventing facts or changing protected terms.
- Turkish aliases learned in one session survive restart without modifying bundled data.
- corrupt/incomplete models never activate; fallback remains usable.

## slice 5 — tray UI and inbound speech

deliver:

- PySide6 tray lifecycle, dashboard, translation window, settings pages, and status/error surfaces.
- ordered Windows SAPI speech worker with voice/rate/volume/mute controls.
- clear history, pause/resume, calibration, diagnostics, model manager, and learned-terms UI.
- startup/setup/degraded/shutdown recovery paths.

gate:

- closing the dashboard leaves the tray service running; Quit releases all resources.
- every inbound player message is displayed and spoken once in order.
- TTS never blocks capture/OCR and never reads system/outbound/unknown lines by default.

## slice 6 — hold-to-talk replies

deliver:

- configurable global key lifecycle and conflict warning.
- microphone capture, faster-whisper adapter, local target-language selection, and command parsing.
- last-speaker targeting, ambiguity chooser, preview/edit/retry, clipboard copy, and toast.
- TTS pause/resume around microphone recording.

gate:

- key-down records and key-up processes; accidental taps are ignored.
- failures and ambiguous targets leave the clipboard unchanged.
- no code focuses the game, pastes, presses Enter, or sends the reply.

## slice 7 — hardening and release

deliver:

- multi-hour soak tests, queue/backpressure tests, startup recovery, privacy audit, and debug-bundle redaction.
- PyInstaller one-folder specification and Inno Setup installer.
- clean-machine Windows verification with no Python installed.
- GitHub Actions test/release workflows, checksums, release notes, and license notices.
- STALZONE and Minecraft manual acceptance checklist.

gate:

- all architecture performance/quality targets are measured with named hardware and fixtures.
- installer, first-run setup, uninstall, model download/removal, and offline restart pass on a clean Windows VM.
- release contains no private screenshots, usernames, chat logs, microphone recordings, or unlicensed model/data payloads.

## user-provided validation inputs

implementation can start immediately. these inputs are needed before game-specific tuning is considered complete:

1. run the slice-0 Windows diagnostic script on the target PC and attach its redacted output.
2. provide 10–20 representative uncropped STALZONE screenshots at the actual resolution.
3. provide several Minecraft Java screenshots with default and resized chat.
4. test signed-off checkpoints on the real gaming PC because cloud/Linux environments cannot validate anti-cheat behavior, Windows capture, microphone hooks, DPI, or actual frame timing.

## first coding action

implement slice 0 in one pull request. do not begin OCR/UI work until the data validators, domain events, settings recovery, storage migrations, CI, and profile skeletons are green.
