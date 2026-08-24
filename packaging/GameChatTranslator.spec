from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

project_root = Path(SPECPATH).parent
source_root = project_root / "src"

datas = [
    (str(project_root / "assets"), "game_chat_translator/resources/assets"),
    (str(project_root / "data"), "game_chat_translator/resources/data"),
    (str(project_root / "profiles"), "game_chat_translator/resources/profiles"),
    (
        str(project_root / "THIRD_PARTY_NOTICES.md"),
        "game_chat_translator/resources",
    ),
    (str(project_root / "LICENSE"), "game_chat_translator/resources"),
    (str(project_root / "licenses"), "game_chat_translator/resources/licenses"),
]
binaries = []
hiddenimports = collect_submodules("game_chat_translator")
hiddenimports += [
    "PySide6",
    "ctranslate2",
    "cv2",
    "faster_whisper",
    "fasttext",
    "llama_cpp",
    "paddle",
    "paddleocr",
    "sounddevice",
    "win32com",
]

binary_packages = (
    "ctranslate2",
    "cv2",
    "fasttext",
    "llama_cpp",
    "paddle",
    "tokenizers",
)
for package in binary_packages:
    binaries += collect_dynamic_libs(package)

datas += collect_data_files("faster_whisper", include_py_files=False)
datas += collect_data_files("paddleocr", include_py_files=False)
datas += collect_data_files("paddlex", include_py_files=False)
sounddevice_data = collect_data_files("_sounddevice_data", include_py_files=False)
datas += [item for item in sounddevice_data if not item[0].casefold().endswith("-asio.dll")]

hiddenimports += [
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32gui",
    "win32process",
]

analysis = Analysis(
    [str(source_root / "game_chat_translator" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging" / "runtime_hook.py")],
    excludes=[
        "argostranslate",
        "av",
        "coverage",
        "matplotlib",
        "modelscope",
        "mypy",
        "openai",
        "scipy",
        "spacy",
        "stanza",
        "tensorflow",
        "torch",
        "pytest",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GameChatTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / "assets" / "app.ico"),
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="GameChatTranslator",
)
