from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def generate(root: Path, output: Path) -> None:
    root = root.resolve(strict=True)
    files: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    payload = {
        "schema_version": 1,
        "root": "GameChatTranslator",
        "file_count": len(files),
        "total_bytes": sum(int(item["size"]) for item in files),
        "files": files,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Hash every file in a frozen artifact")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
