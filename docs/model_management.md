# Model management

Models are acquired only through an explicit `DownloadCommand` backed by a validated allowlist
manifest entry. The lifecycle service never derives a filename from a URL: managed filenames come
only from the validated model ID. HTTP is injected. Redirects are rejected except for the explicit
Hugging Face origin-to-Hugging Face CDN policy used by the allowlisted GGUF entries; size and digest
verification remain mandatory after that redirect. Tests use no live network.

Downloads enforce the manifest size, available disk space, a 16 GiB application ceiling, streamed
SHA-256 verification, cancellation, and at most five attempts. A retained partial may resume only
when the source explicitly supports ranges; otherwise it is discarded and restarted. A completed
payload must pass its provider health check before atomic activation. Failed verification,
activation, or health checks preserve the last-known-good active model.

The shipped manifest offers Apache-2.0 Qwen 2.5 GGUF choices for low-CPU, balanced-CPU, and GPU
tiers. Hardware recommendation reads only local memory/CPU metadata; GPU compatibility is an
explicit capability input and can always be overridden by the user. Verified active records are
stored in SQLite and are rechecked for containment, size, digest, and health before restart reuse.

Removal is limited to manager-owned installed paths and is rejected while a model is active or
marked in use. Callers explicitly deactivate a model before removing it.
Callers receive structured outcomes and safe error codes; captured chat and filesystem details are
never included in outcome messages.

`CoreRuntime` is the composition boundary for the current setup CLI and the Slice-5 dashboard. It
loads only the bundled manifest, binds every command to an exact manifest entry, wires SQLite model
and learning stores, restores verified models, creates isolated providers/router/pipeline, and owns
shutdown. `game-chat-translator --list-models`, `--download-model MODEL_ID`, and
`--remove-model MODEL_ID` expose size/license choices and explicit setup without enabling downloads
during normal monitoring.
