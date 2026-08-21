from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from dataclasses import asdict

from game_chat_translator import __version__


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Offline-first game chat translator")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--packaging-smoke",
        action="store_true",
        help="Validate that the packaged entry point can start without opening the tray UI.",
    )
    model_actions = parser.add_mutually_exclusive_group()
    model_actions.add_argument(
        "--list-models", action="store_true", help="List trusted local model setup choices."
    )
    model_actions.add_argument(
        "--download-model", metavar="MODEL_ID", help="Explicitly download and verify one model."
    )
    model_actions.add_argument(
        "--remove-model", metavar="MODEL_ID", help="Deactivate and remove one installed model."
    )
    args = parser.parse_args(argv)
    if args.packaging_smoke:
        from game_chat_translator.resource_paths import bundled_resource_root
        from game_chat_translator.validation.validators import validate_repository

        resource_root = bundled_resource_root()
        validate_repository(resource_root)
        if not (resource_root / "assets" / "app.ico").is_file():
            raise RuntimeError("packaged application icon is unavailable")
        return 0
    if args.list_models or args.download_model or args.remove_model:
        from game_chat_translator.core_runtime import CoreRuntime

        try:
            with CoreRuntime() as runtime:
                if args.list_models:
                    payload = [asdict(option) for option in runtime.model_options()]
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                    return 0
                if args.download_model:
                    last_percent = -1

                    def progress(received: int, total: int) -> None:
                        nonlocal last_percent
                        percent = int(received * 100 / total)
                        if percent != last_percent:
                            last_percent = percent
                            print(f"model download: {percent}%", file=sys.stderr)

                    outcome = runtime.download_model(args.download_model, progress=progress)
                else:
                    assert args.remove_model is not None
                    outcome = runtime.remove_model(args.remove_model)
                print(f"{outcome.code}: {outcome.message}")
                return 0 if outcome.status.value in {"activated", "removed"} else 2
        except (OSError, RuntimeError, ValueError) as exc:
            del exc
            print("model setup could not be completed safely", file=sys.stderr)
            return 2
    from game_chat_translator.desktop import run_desktop_application

    return run_desktop_application()


if __name__ == "__main__":
    raise SystemExit(main())
