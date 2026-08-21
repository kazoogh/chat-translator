# Translation evaluation status

Slice 4 provides a deterministic rubric harness and stable ID-based held-out split. The rubric
reports meaning, naturalness, slang, tone, profanity, protected-term preservation, and invention
separately. High-confidence and low-confidence rows have separate denominators; low-confidence rows
must never be used to inflate the required high-confidence pass rate.

The harness loads all 211 reviewed corpus rows, derives stable content IDs, and freezes a SHA-256
held-out bucket. It reports 192 exact-high-confidence rows separately from 19 medium/ambiguous rows.
Those denominators are test-gated and cannot be padded with generated examples.

Portable tests use fake local providers and synthetic rubric cases. They prove routing, fallback,
cancellation, timeout/error mapping, bounded retry/cache behavior, prompt bounds, and evaluator
accounting. They do **not** establish real-model translation quality. The architecture's 90% reviewed
high-confidence corpus gate remains provisional until an allowlisted local model is installed and
the frozen held-out corpus is evaluated without tuning against its expected outputs. Invention and
tone judgments still require independent human review; the loader does not pretend missing corpus
annotations are automatic evidence.

Normal translation requires no network provider. Native providers run in a socket-denied subprocess
that is terminated on timeout, cancellation, generation replacement, or shutdown. Routing is local
contextual model, installed-package-only Argos, exact reviewed-corpus fallback, then unchanged
original text. The reviewed fallback translates only exact corpus phrases and therefore cannot
invent a translation for an unknown line. The router never retries cancellations.
