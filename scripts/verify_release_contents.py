from __future__ import annotations

import argparse
from pathlib import Path

_FORBIDDEN_COMPONENTS = {
    "argostranslate",
    "av",
    "av.libs",
    "coverage",
    "modelscope",
    "mypy",
    "pynput",
    "pyautogui",
    "pytest",
    "spacy",
    "stanza",
    "tensorflow",
    "torch",
}
_FORBIDDEN_SUFFIXES = {".gguf", ".pdiparams", ".wav", ".wave"}


def verify(root: Path) -> None:
    root = root.resolve(strict=True)
    violations: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        components = {part.casefold() for part in relative.parts}
        if components & _FORBIDDEN_COMPONENTS:
            violations.append(relative.as_posix())
        if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
            violations.append(relative.as_posix())
        if path.name.casefold() == "model.bin":
            violations.append(relative.as_posix())
        if path.name.casefold().endswith("-asio.dll"):
            violations.append(relative.as_posix())
        if path.name.casefold().startswith("cudnn"):
            violations.append(relative.as_posix())
    if violations:
        joined = "\n".join(sorted(set(violations))[:100])
        raise RuntimeError(f"forbidden release payloads were found:\n{joined}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject private or unsupported release payloads")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    verify(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
