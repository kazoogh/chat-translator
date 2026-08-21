from __future__ import annotations

import argparse

from game_chat_translator import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline-first game chat translator")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--packaging-smoke",
        action="store_true",
        help="Validate that the packaged entry point can start without opening the tray UI.",
    )
    args = parser.parse_args(argv)
    if args.packaging_smoke:
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
