# Game Chat Translator 0.1.2 prerelease

This repair release makes first-run setup functional in the packaged Windows app:

- the installer now includes the SQLite migration files required to open clean local storage;
- the frozen-runtime gate creates and exercises a brand-new database, preventing this packaging
  regression from returning;
- model cards now load their real installed state and show download progress and completion;
- setup actions explain why monitoring is unavailable instead of presenting inert controls;
- calibration now covers the full display with one frozen image and renders the selected crop
  correctly;
- the Capture page displays the saved chat crop as a memory-only preview;
- local OCR validates the selected chat area when the verified OCR bundle is available;
- translations remain embedded in the main Status page.

No API key, paid service, or cloud account is required. Install the required 12.5 MiB OCR bundle
from **Translation Models**, then calibrate the complete in-game chat panel. The built-in offline
translator is included. Voice recognition and larger contextual translation models are optional.

The installer is unsigned. Windows may show a reputation warning. Verify the adjacent SHA-256
file before running it. Model weights are downloaded separately after explicit user action and
are not bundled.
