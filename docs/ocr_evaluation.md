# OCR evaluation status

Slice 2 establishes the PaddleOCR 3.x adapter contract, deterministic preprocessing, visual-line
grouping, rolling fuzzy tracking, bounded queues, a restartable provider subprocess, and a local
fixture annotation helper. The
portable test suite uses synthetic polygons and provider results to exercise those contracts.

Normal OCR inference runs in a subprocess with outbound Python socket access denied. A timed-out,
cancelled, or obsolete worker is terminated; the next request starts a clean worker. Provider
exceptions cross that boundary only as safe error codes.

The repository does not contain reviewed STALZONE screenshots. Consequently, the architecture's
held-out real-game OCR/player-message recall target is **unmeasured**, not passed. Synthetic inputs
must never be reported as evidence for that target.

To create eligible evidence:

1. Run `python scripts/capture_fixture.py IMAGE --fixture-id ID --source-text TEXT --language ru
   --confirm-private-content` for explicitly selected screenshots.
2. Keep the generated `local_fixtures/` content local until every player name, message, window
   title, and unrelated pixel has been reviewed for publication.
3. Split fixtures deterministically by stable fixture ID before tuning thresholds. Do not inspect
   held-out images while tuning.
4. Report the denominator, excluded low-confidence lines, raw OCR recall, and player-message recall.
   Preserve every failure fixture; do not lower the target or remove failures after evaluation.

Normal application execution never invokes the fixture helper and never persists screenshots.
