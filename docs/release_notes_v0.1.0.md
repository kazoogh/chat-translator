# Game Chat Translator 0.1.0 prerelease

This Windows x64 prerelease provides the complete offline-first desktop workflow:

- calibrated game-window chat capture for STALZONE and Minecraft profiles;
- local OCR, classification, Russian/English/Turkish language analysis, translation, and SAPI announcements;
- observation-only global shortcuts and hold-to-talk English replies copied to the clipboard;
- explicit, checksummed local model setup with no normal-workflow network dependency;
- privacy-redacted diagnostics, opt-in history, and selectable user-data retention on uninstall.

The installer is unsigned. Windows may show a reputation warning. Verify the adjacent SHA-256 file before running it.

Known prerelease limitations:

- model weights are downloaded separately after explicit user action and are not bundled;
- real-game OCR/classification/translation quality gates require the privacy-reviewed screenshots and corpus listed in the repository validation checklist;
- physical multi-monitor/DPI, microphone, tray, game hotkey-conflict, and long-duration soak checks remain hardware/manual acceptance items;
- no software can guarantee a game publisher's anti-cheat approval. The application uses documented window capture and observation-only input APIs and never injects, reads game memory, or simulates input.
