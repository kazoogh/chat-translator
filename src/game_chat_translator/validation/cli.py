from __future__ import annotations

import argparse
from pathlib import Path

from game_chat_translator.validation.validators import DataValidationError, validate_repository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Game Chat Translator bundled resources")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        validate_repository(args.root.resolve())
    except DataValidationError as exc:
        parser.exit(1, f"validation failed: {exc}\n")
    print("profiles, glossary, corpus, and model manifest are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
