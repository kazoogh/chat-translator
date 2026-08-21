# Slice 5 physical Windows checklist

These checks require a real interactive Windows desktop and are not replaced by hosted CI. Passing
them does not claim or guarantee anti-cheat approval.

- Install the pinned UI, Windows, and capture extras; launch without an active console error.
- Verify the original application icon at 16, 20, 24, 32, 48, and high-DPI tray/taskbar sizes.
- Close the dashboard with the X button and Alt+F4; confirm the tray remains and reopens one dashboard.
- Use explicit Quit during idle, active speech, a model download, and calibration; confirm the tray,
  SAPI output, model child processes, and storage worker stop once.
- Log off or shut down Windows with the app running and confirm the same bounded shutdown path.
- Disconnect or disable a voice and confirm the dashboard enters a safe degraded state while visual
  translations remain usable.
- Send three consecutive inbound player fixtures and hear them once in exact order. Interleave
  outbound, system, and unknown fixtures and confirm they remain silent.
- Mute during an utterance and confirm current/queued speech stops; unmute and confirm only newly
  accepted messages play. Check rate, volume, and every listed local voice.
- Confirm the native SAPI smoke writes a non-empty RIFF/WAVE file without using the speaker device.
- Open a game, request calibration, switch focus during the delay, and verify only the frozen client
  area appears. Repeat at 100%, 125%, 150%, and 200% DPI and across negative-origin monitors.
- Move/resize the always-on-top translation window on each display, restart, and verify geometry is
  restored to the matching display layout.
- Confirm history is absent from SQLite by default. Enable a finite retention, restart, purge expired
  rows, then Clear History and verify calibrations and accepted learned terms remain.
- Open model, learned-term, and diagnostics pages. Confirm opening pages makes no network request,
  download requires a click, and diagnostics contain no chat, username, clipboard, audio, screenshot,
  path, or window-title canaries.
- Play with STALZONE and Minecraft Java using only calibrated screen capture. Confirm the app never
  reads process memory, injects, hooks rendering, captures packets, focuses the game, pastes, presses
  Enter, or simulates game input.
