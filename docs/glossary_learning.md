# Local glossary learning

The learner is a pure-domain, local-only component. It records only keyed, per-install HMAC context
identity plus confidence, OCR stability, and timestamps. Speaker/message inputs never enter SQLite
and hashes cannot be linked across installations. It does not export chat snippets.

An alias becomes active automatically only when it maps to an already-known canonical game term
and has evidence from at least three distinct messages and two distinct speakers. Mean translation
confidence and OCR stability must both be at least 0.9. New canonical meanings remain pending for
user confirmation. Existing-layer and candidate meaning conflicts are blocked.

Usernames, URLs, numbers, sentences, and a conservative set of isolated insults are excluded.
Duplicate message IDs add no evidence. Rejected and blocked aliases remain suppressed until a user
explicitly changes their status. Active candidates stop accumulating evidence, and pending evidence
is capped at 64 records per alias to bound memory and database writes.

`GlossaryLearner.export_overlay()` produces a versioned JSON-safe DTO. Import validates the DTO and
rejects conflicts. `validated_local_glossary()` returns the shared validated glossary schema and is
passed as the local argument to `GlossaryResolver(bundled, community, local)`. The resolver's order
therefore remains bundled, then community, then local, with local aliases taking precedence.
Bundled/community inputs are never mutated.
