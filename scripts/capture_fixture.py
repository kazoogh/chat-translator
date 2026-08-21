from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly ingest and annotate a local OCR fixture (never uploads content)."
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("local_fixtures"))
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--source-text", action="append", required=True)
    parser.add_argument("--language", action="append", required=True)
    parser.add_argument("--confirm-private-content", action="store_true", required=True)
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error("image does not exist")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.fixture_id) is None:
        parser.error("fixture ID must contain only letters, numbers, dot, underscore, or hyphen")
    if len(args.source_text) != len(args.language):
        parser.error("provide one --language for each --source-text")
    if not args.confirm_private_content:
        parser.error("explicit --confirm-private-content is required")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = args.image.suffix.casefold()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp"}:
        parser.error("fixture image must be PNG, JPEG, or BMP")
    destination = output_dir / f"{args.fixture_id}{suffix}"
    annotation = output_dir / f"{args.fixture_id}.json"
    if destination.exists() or annotation.exists():
        parser.error("fixture ID already exists")
    shutil.copyfile(args.image, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1,
        "fixture_id": args.fixture_id,
        "image_file": destination.name,
        "sha256": digest,
        "captured_at": datetime.now(UTC).isoformat(),
        "privacy_reviewed_for_publication": False,
        "lines": [
            {"source_text": text, "language": language}
            for text, language in zip(args.source_text, args.language, strict=True)
        ],
    }
    annotation.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"fixture stored locally: {annotation}")
    print("privacy_reviewed_for_publication remains false; do not commit without review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
