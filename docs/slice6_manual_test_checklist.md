# Slice 6 physical Windows acceptance checklist

These checks require real Windows hardware and are not inferred from hosted CI or synthetic audio.
Record the Windows build, CPU, GPU, RAM, microphone, game/profile, model revision, and sample count.

- Install the verified local speech model through the dashboard and restart offline. Confirm the
  model remains ready and no network request occurs during transcription.
- With the game focused, hold the configured key for normal English speech, then release it. Confirm
  the game still receives its own key event and the application never changes focus, pastes, presses
  Enter, or sends a message.
- Confirm SAPI pauses before the microphone opens, inbound announcements accumulate in FIFO order,
  and speech resumes exactly once after success, cancellation, ambiguity, and provider failure.
- Exercise a short tap, autorepeat, missed release, device disconnect, mute/pause, Clear History, and
  shutdown while recording. Confirm the microphone closes and the existing clipboard is unchanged.
- Exercise plain replies and `reply to <name>:` with exact, missing, similar, Unicode, and ambiguous
  recent speakers. Confirm ambiguity requires a dashboard selection and never silently guesses.
- Edit a ready draft and retry a deliberately failed clipboard write. Confirm only the explicit retry
  changes the clipboard and the generic Windows notification contains no transcript or player name.
- Test quiet/noisy rooms and representative accents. Report release-to-copy p50/p95 separately; the
  product target is under three seconds, but it remains a limitation until measured on named hardware.
- Inspect `%TEMP%`, application data, logs, diagnostics, crash artifacts, and history after the run.
  Confirm no PCM, transcript, reply draft, clipboard content, or player name was persisted by default.

Anti-cheat compatibility must be assessed per game/vendor. External observation and manual clipboard
delivery reduce integration risk but do not guarantee approval.
