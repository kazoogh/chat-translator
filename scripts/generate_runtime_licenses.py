from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
from pathlib import Path

RUNTIME_DISTRIBUTIONS = (
    "aistudio-sdk",
    "annotated-types",
    "anyio",
    "bce-python-sdk",
    "certifi",
    "cffi",
    "chardet",
    "charset-normalizer",
    "click",
    "cloudpathlib",
    "colorlog",
    "comtypes",
    "crc32c",
    "ctranslate2",
    "diskcache",
    "dxcam",
    "faster-whisper",
    "fasttext-wheel",
    "filelock",
    "flatbuffers",
    "fsspec",
    "future",
    "hf-xet",
    "httpcore",
    "httpx",
    "huggingface-hub",
    "idna",
    "imagesize",
    "jinja2",
    "llama-cpp-python",
    "MarkupSafe",
    "mss",
    "numpy",
    "onnxruntime",
    "opencv-contrib-python",
    "opt-einsum",
    "packaging",
    "paddleocr",
    "paddlepaddle",
    "paddlex",
    "pandas",
    "pillow",
    "platformdirs",
    "prettytable",
    "protobuf",
    "psutil",
    "pyclipper",
    "pycparser",
    "pycryptodome",
    "pydantic",
    "pydantic-core",
    "pypdfium2",
    "PySide6",
    "PySide6-Addons",
    "PySide6-Essentials",
    "pywin32",
    "PyYAML",
    "regex",
    "requests",
    "ruamel.yaml",
    "shapely",
    "shiboken6",
    "sounddevice",
    "tokenizers",
    "tqdm",
    "typing-extensions",
    "typing-inspection",
    "tzdata",
    "ujson",
    "urllib3",
    "wcwidth",
)


def generate(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    missing: list[str] = []
    for requested_name in RUNTIME_DISTRIBUTIONS:
        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requested_name)
            continue
        normalized = distribution.metadata["Name"] or requested_name
        destination = output / normalized.replace("/", "_")
        destination.mkdir(exist_ok=True)
        copied: list[str] = []
        candidates = set(distribution.metadata.get_all("License-File") or ())
        for item in distribution.files or ():
            basename = Path(str(item)).name.casefold()
            if basename.startswith(("license", "copying", "notice", "copyright")):
                candidates.add(str(item))
        for candidate in sorted(candidates):
            source = Path(distribution.locate_file(candidate))
            if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
                continue
            safe_name = candidate.replace("\\", "__").replace("/", "__").replace(":", "_")
            target = destination / safe_name[-180:]
            if target.exists() and target.read_bytes() == source.read_bytes():
                copied.append(str(target.relative_to(output)))
                continue
            shutil.copyfile(source, target)
            copied.append(str(target.relative_to(output)))
        entries.append(
            {
                "name": normalized,
                "version": distribution.version,
                "license_expression": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or "not declared in wheel metadata",
                "license_files": copied,
            }
        )
    if missing:
        raise RuntimeError(f"runtime distributions are missing: {', '.join(missing)}")
    manifest: dict[str, object] = {"schema_version": 1, "distributions": entries}
    (output / "runtime-artifact-inventory.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy exact runtime wheel license materials")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
