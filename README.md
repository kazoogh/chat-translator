# game chat translator

an offline-first Windows tray application that watches a user-calibrated in-game chat region, recognizes new player messages, translates them into natural English, and optionally reads them aloud. hold-to-talk replies are transcribed and translated locally, then copied to the clipboard for the user to paste manually.

## status

build slices 0–7 are implemented: typed foundations, recoverable persistence, documented Win32
foreground metadata, calibrated-region capture with fallback, profile debounce, layout
compatibility checks, the frozen-screenshot calibration interface, PaddleOCR 3.x adapter,
profile-driven preprocessing, rolling line tracking, conservative profile-driven classification,
validated profile resources and overrides, layered glossary protection, and local Russian,
English, Turkish, and mixed-script analysis are available. Slice 4 adds bounded contextual local
translation with a process-isolated llama.cpp adapter, installed-package-only Argos fallback,
an always-available reviewed-corpus fallback, checksummed model setup and restart validation,
generational FIFO publication, and evidence-gated local glossary learning. The complete
tray/dashboard, calibrated live monitoring coordinator, explicit checksum-verified PaddleOCR setup,
and ordered Windows SAPI inbound speech are now available with memory-only history by default,
explicit local model/learning actions, privacy-redacted diagnostics, and deterministic shutdown.
Slice 6 adds observation-only configured-key handling, bounded memory-only microphone capture,
process-isolated local faster-whisper transcription, exact recent-speaker targeting, editable reply
drafts, and UI-thread clipboard delivery without focus, paste, Enter, or send automation. Slice 7
adds the PyInstaller one-folder application, per-user Inno Setup installer, frozen native/subprocess
smoke, silent install/uninstall acceptance, exact file/checksum inventories, pinned release workflow,
privacy-redacted ZIP support bundle, and accelerated bounded-queue soak. The remaining physical and
quality evidence is tracked honestly in [`docs/release_acceptance.md`](docs/release_acceptance.md).

Slice 2's real-game recall gate remains provisional until privacy-reviewed STALZONE screenshots are
available; synthetic contract tests are not counted as recall evidence. See
[`docs/ocr_evaluation.md`](docs/ocr_evaluation.md).

Slice 3's deterministic post-OCR classifier gate is green, while its real-game color/language
evidence remains provisional. Scope and limitations are documented in
[`docs/classification_evaluation.md`](docs/classification_evaluation.md).

Slice 4's portable routing, offline-process, model-integrity, persistence, and learning gates are
green. The reviewed real-model 90% translation-quality gate remains provisional until the selected
allowlisted model is run against the held-out corpus; see
[`docs/translation_evaluation.md`](docs/translation_evaluation.md).

Slice 5's calibrated capture-to-presentation coordinator, controller, privacy, FIFO speech,
fake-COM, offscreen Qt, and native SAPI file-synthesis gates are automated. Real-game OCR recall,
tray, speaker, game-focus, DPI, and multi-monitor checks remain physical;
see [`docs/slice5_manual_test_checklist.md`](docs/slice5_manual_test_checklist.md).

Slice 6's deterministic key, audio, isolation, targeting, translation, generation, and clipboard
gates are automated. Real microphone/accent/noise performance and the under-three-second target
remain physical and provisional; see [`docs/slice6_manual_test_checklist.md`](docs/slice6_manual_test_checklist.md).

Slice 7's release mechanics are automated on Windows. The real-game, named-hardware performance,
multi-hour, and clean-VM physical checklist remains provisional and is never inferred from hosted
CI or synthetic fixtures; see [`docs/release_acceptance.md`](docs/release_acceptance.md).

## product boundaries

- screen capture through normal Windows APIs only.
- no process-memory reading, DLL injection, renderer hooks, packet inspection, or automated game input.
- no automatic pasting or message sending.
- no paid API, subscription, account, telemetry, or cloud dependency for core operation.
- external capture lowers integration risk but does not guarantee approval by every game or anti-cheat vendor.

## planned v1

- Windows 10/11 x64 tray application and dashboard.
- screenshot-style chat-region calibration.
- STALZONE and Minecraft Java profiles plus a generic manual profile.
- multilingual OCR and message-level language detection.
- natural local translation with slang, profanity, context, and game terms preserved.
- live local glossary learning with evidence/confidence controls.
- inbound text-to-speech.
- hold-to-talk English reply, local translation, clipboard copy, and notification.
- one Windows installer and GitHub Release assets.

## project documents

- [`project_architecture.md`](project_architecture.md): product and system specification.
- [`BUILD_PLAN.md`](BUILD_PLAN.md): implementation slices, gates, and dependency order.
- [`docs/runtime_contracts.md`](docs/runtime_contracts.md): domain events, service interfaces, lifecycle, and error contracts.
- [`data/README.md`](data/README.md): versioned glossary and translation-corpus rules.

## language data

- 211 anonymized STALZONE translation examples.
- 77 reviewed STALZONE glossary terms.
- bundled language assets are immutable at runtime; accepted personal learning is stored in the user's local overlay.

## development

Install Python 3.12, clone the repository, and run the one-command bootstrap from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

The script installs the pinned `uv` bootstrap tool when needed, creates `.venv`, installs the locked
development environment, validates bundled resources, and runs formatting, lint, type, and test
gates. Launch the current application entry point with:

```powershell
python -m uv run game-chat-translator
```

Collect a privacy-redacted hardware and foreground-window diagnostic with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnostics.ps1 -Output diagnostic.json
```

Build and verify the supported Windows installer from the locked combined runtime with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -Version 0.1.1
powershell -ExecutionPolicy Bypass -File .\scripts\test_installer.ps1
```

The installer and adjacent SHA-256 file are written under `artifacts\installer`. Model weights are
never bundled and are downloaded only through explicit, revision-pinned, checksum-verified setup.

## license

Original project code is Apache-2.0. Models and third-party datasets retain their own licenses.
Release builds ship generated runtime notices, exact artifact inventories, GNU LGPL/GPL terms, and
Qt replacement/relinking instructions; downloadable model weights are not redistributed.
