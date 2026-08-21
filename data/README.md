# language data

this directory contains versioned, human-reviewed language assets used by game profiles and regression tests.

## files

- `glossaries/stalzone.v1.json`: canonical STALZONE terms and observed aliases.
- `corpora/stalzone.translation.v1.jsonl`: one JSON object per translation example.

the corpus is evaluation and prompt-example data. it is not automatically used for model training. public rows must not contain private screenshots, account identifiers, or unnecessary player-name annotations.

## versioning

create a new versioned file for schema-breaking or meaning-changing revisions. typo fixes and additional reviewed entries may update the current version before the first tagged release.
