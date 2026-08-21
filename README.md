# game chat translator

an offline-first Windows tray application that watches a user-calibrated in-game chat region, recognizes new player messages, translates them into natural English, and optionally reads them aloud. hold-to-talk replies are transcribed and translated locally, then copied to the clipboard for the user to paste manually.

## status

build slices 0–4 are implemented: typed foundations, recoverable persistence, documented Win32
foreground metadata, calibrated-region capture with fallback, profile debounce, layout
compatibility checks, the frozen-screenshot calibration interface, PaddleOCR 3.x adapter,
profile-driven preprocessing, rolling line tracking, conservative profile-driven classification,
validated profile resources and overrides, layered glossary protection, and local Russian,
English, Turkish, and mixed-script analysis are available. Slice 4 adds bounded contextual local
translation with a process-isolated llama.cpp adapter, installed-package-only Argos fallback,
an always-available reviewed-corpus fallback, checksummed model setup and restart validation,
generational FIFO publication, and evidence-gated local glossary learning. The complete
tray/dashboard, voice, and release packaging are built in the subsequent slices in
[`BUILD_PLAN.md`](BUILD_PLAN.md).

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

## license

original project code is planned under Apache-2.0. models and third-party datasets retain their own licenses and are reviewed before redistribution.
