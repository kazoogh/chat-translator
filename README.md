# game chat translator

an offline-first Windows tray application that watches a user-calibrated in-game chat region, recognizes new player messages, translates them into natural English, and optionally reads them aloud. hold-to-talk replies are transcribed and translated locally, then copied to the clipboard for the user to paste manually.

## status

architecture and initial STALZONE language data are ready. application implementation begins with build slice 0 in [`BUILD_PLAN.md`](BUILD_PLAN.md).

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

the source bootstrap and run commands will be added in build slice 0. commands are intentionally not documented before they exist and pass on Windows.

## license

original project code is planned under Apache-2.0. models and third-party datasets retain their own licenses and are reviewed before redistribution.
