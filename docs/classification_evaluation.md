# Classification evaluation status

The Slice 3 gate uses a deterministic held-out bucket selected only from stable fixture IDs. The
named text fixture set covers Russian, English, Turkish, mixed language, item links, punctuation,
low OCR confidence, player bodies containing system vocabulary, known and near-miss system text,
explicit outbound markers, and the configured user's own messages. Synthetic system/outbound
families provide a denominator above 50 in the held-out bucket; CI requires at least 95% player
recall and less than 1% false announcements.

Current deterministic bucket 0 contains 86 of 493 fixtures: 28 inbound and 58 expected-silent.
The measured regression result is 100% inbound recall and 0% false announcements on that bucket.

These fixtures validate classifier behavior after OCR. Deterministic tests also validate mapping
OCR polygons back to configured colors in the unscaled source frame, but they do not measure color
prevalence, screenshot OCR recall, or unseen STALZONE system formats. This quantitative result is a
synthetic regression gate, not an empirical real-game error rate. The Slice 3 empirical gate remains
provisional alongside the screenshot evidence in `docs/ocr_evaluation.md`; failures discovered there
must be added as named fixtures without deleting or re-labeling prior failures.

The local language interface includes a manifest-bound, checksummed, lazy fastText adapter and a
deterministic script/lexical fallback. CI trains, loads, and predicts with a tiny local model to
exercise the pinned Windows binding, including its NumPy 2 compatibility path. An allowlisted
production language-ID model and a diverse privacy-reviewed language fixture set remain acceptance
items; the small fallback vocabulary is not presented as a complete language-quality measurement.

Unknown and low-confidence lines are always returned for visual display with `should_announce`
false. The test gate never treats an unknown decision as safe to announce.
