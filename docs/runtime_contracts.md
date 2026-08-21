# runtime contracts

this document fixes subsystem boundaries before provider code is written. names may gain fields through backward-compatible changes, but their meaning and ownership must remain stable.

## rules

- use frozen dataclasses or equivalent immutable Pydantic models at worker boundaries.
- timestamps are timezone-aware UTC plus monotonic timing where latency/order matters.
- IDs are opaque UUIDs; display text is never used as identity.
- provider-specific objects are converted at the adapter boundary.
- every event includes `event_id`, `session_id`, `created_at`, and optional `correlation_id`.
- queues are bounded and declare whether they replace, reject, or preserve older work.
- errors are structured data; workers do not communicate failures only through logs.

## core value objects

| type | required fields | notes |
| --- | --- | --- |
| `WindowIdentity` | process ID, executable, title, class, client bounds, monitor ID, DPI | process ID is transient and never the profile key |
| `GameProfileRef` | profile ID, version, source, trust state | source is bundled, community, or user |
| `ChatRegion` | normalized x/y/width/height, layout ID, reference client size/DPI | screen coordinates are derived at runtime |
| `CapturedFrame` | frame ID, timestamp, profile/layout IDs, region, RGB/BGRA image handle | image lifetime is explicit and bounded |
| `OcrFragment` | text, confidence, polygon, script | immutable provider-neutral result |
| `ChatLine` | line ID, raw text, normalized text, boxes, confidence, visual order | exists before player/system classification |
| `ClassifiedMessage` | message ID, direction/class, speaker, channel, body, confidence | class is inbound, outbound, system, or unknown |
| `LanguageAnalysis` | primary language, spans, confidence, protected terms | supports mixed-language text |
| `TranslationResult` | source, target, natural text, provider/model, confidence, warnings | never overwrites the source object |
| `SpeechItem` | message ID, announcement text, priority, expiry | speech queue preserves normal chat order |
| `ReplyDraft` | transcript, target speaker/language, translated text, confidence, status | clipboard write occurs only after successful validation |
| `GlossaryCandidate` | observed text, proposed canonical term, language, evidence, confidence, status | status is pending, active, rejected, or blocked |

## event sequence

1. `ForegroundWindowChanged`
2. `ActiveProfileResolved` or `ProfileResolutionFailed`
3. `FrameCaptured`
4. `OcrCompleted` or `ProviderFailed`
5. `NewChatLinesDetected`
6. `MessagesClassified`
7. `LanguageAnalyzed`
8. `TranslationCompleted` or `TranslationDegraded`
9. `TranslationPublished`
10. `SpeechQueued`

reply sequence:

1. `ReplyRecordingStarted`
2. `ReplyRecordingStopped` or `ReplyRecordingCancelled`
3. `ReplyTranscribed`
4. `ReplyTargetResolved` or `ReplyTargetAmbiguous`
5. `ReplyTranslated`
6. `ReplyDraftReady`
7. `ReplyCopied` only after a successful clipboard operation

## service interfaces

| interface | key operations | ownership |
| --- | --- | --- |
| `ForegroundWindowProvider` | get active window metadata | detection worker |
| `ProfileResolver` | resolve profile/layout with confidence | detection worker |
| `CaptureProvider` | start, next frame, pause, close | capture worker |
| `OcrProvider` | recognize frame with cancellation/timeout | OCR worker |
| `LineTracker` | accept ordered lines, emit new lines, reset on profile/layout change | OCR worker |
| `MessageClassifier` | classify lines with active profile | classifier worker |
| `LanguageDetector` | detect message/spans | translation worker |
| `GlossaryResolver` | protect/resolve bundled, community, local terms | translation worker; storage through repository |
| `TranslationProvider` | translate request, health check, close | translation/reply workers through serialized model access |
| `SpeechProvider` | speak, cancel, enumerate voices, close | speech worker |
| `AudioRecorder` | begin, finish, cancel | microphone worker |
| `TranscriptionProvider` | transcribe audio, health check | voice-recognition worker |
| `ClipboardProvider` | copy validated draft | UI/application service only |
| `StateRepository` | transactional domain persistence | storage service; no raw SQL outside storage package |

## queue policy

| queue | capacity/policy |
| --- | --- |
| captured frames | capacity 1, newest replaces stale frame |
| OCR results | capacity 2, discard results from obsolete profile/layout generations |
| classified messages | bounded FIFO, preserve visual order |
| translation requests | bounded FIFO, never silently drop accepted player messages |
| speech items | bounded FIFO; expired low-priority diagnostics may drop, normal chat may not |
| reply jobs | one active draft; a second attempt requires cancel/replace confirmation |
| UI events | coalesce status/progress events; preserve messages/errors |

## generation and cancellation

- profile, layout, model, and application configuration each have a monotonically increasing generation number.
- work captures the relevant generations when queued.
- results from an obsolete generation are discarded before publication.
- pause cancels capture/OCR production but does not destroy configuration.
- calibration pauses monitoring and increments the layout generation after save.
- model replacement health-checks the new provider before incrementing the model generation.
- shutdown cancels capture first, then compute providers, then speech/audio/hotkeys, then UI/storage.

## structured errors

`AppError` includes:

- stable code.
- subsystem.
- severity: info, recoverable, degraded, or fatal.
- safe user message.
- technical detail for diagnostics.
- retryability and suggested action.
- correlation ID and causal error code.

provider exceptions are caught at adapter boundaries. raw OCR/chat/audio content is excluded from errors and logs unless the user explicitly enables diagnostic content capture.

## persistence contracts

- configuration writes use validate → temporary file → flush → atomic replace → retain last-known-good backup.
- SQLite uses WAL, foreign keys, busy timeout, explicit transactions, and numbered forward migrations.
- bundled profiles/glossaries are immutable; user changes live in overrides/local overlays.
- learned-term evidence stores hashes and minimal snippets by default, not full conversation history.
- clearing history does not delete calibrations or accepted glossary aliases; each data class has its own clear/export control.
- uninstall offers a separate explicit choice to retain or remove `%LOCALAPPDATA%/GameChatTranslator` data.

## provider health and fallback

providers report `uninitialized`, `loading`, `ready`, `degraded`, `failed`, or `stopped`.

- a health check never blocks the UI thread.
- repeated failures use bounded exponential backoff.
- GPU initialization failure retries the compatible CPU provider once, then surfaces degraded state.
- contextual translation failure tries lightweight offline translation; if that fails, publish original text with a warning and do not fabricate a translation.
- TTS failure leaves the visual translation intact.
- clipboard failure leaves the draft visible and reports that it was not copied.

## compatibility contract

- profiles, glossaries, corpora, settings, database, and model manifests each version independently.
- readers reject unknown major schema versions and ignore documented unknown minor fields.
- migrations and validators include fixtures for the previous supported version.
- profile packages contain data only and cannot import or execute code.
