# Third-party notices

This inventory is maintained alongside `uv.lock`. Original project code is Apache-2.0.
Dependencies retain their own licenses; the exact installed metadata must be regenerated and
reviewed before every release artifact is published.

| Component | Pinned version | License | Source | Distribution |
| --- | ---: | --- | --- | --- |
| Pydantic | 2.11.7 | MIT | https://github.com/pydantic/pydantic | source/runtime dependency |
| platformdirs | 4.3.8 | MIT | https://github.com/tox-dev/platformdirs | source/runtime dependency |
| Hatchling | 1.27.0 | MIT | https://github.com/pypa/hatch | build only |
| pytest | 8.4.1 | MIT | https://github.com/pytest-dev/pytest | development only |
| Ruff | 0.12.8 | MIT | https://github.com/astral-sh/ruff | development only |
| mypy | 1.17.1 | MIT | https://github.com/python/mypy | development only |
| pre-commit | 4.3.0 | MIT | https://github.com/pre-commit/pre-commit | development only |
| PyInstaller | 6.15.0 | GPL-2.0-or-later with bootloader exception | https://pyinstaller.org | build only / bootloader distributed |
| pywin32 | 311 | PSF-2.0 | https://github.com/mhammond/pywin32 | optional Windows runtime |
| psutil | 7.0.0 | BSD-3-Clause | https://github.com/giampaolo/psutil | optional Windows runtime |
| dxcam | 0.0.5 | MIT | https://github.com/ra1nty/DXcam | optional Windows capture |
| mss | 10.0.0 | MIT | https://github.com/BoboTiG/python-mss | optional capture fallback |
| PySide6 | 6.9.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://code.qt.io/cgit/pyside/pyside-setup.git | optional desktop bindings |
| PySide6 Essentials | 6.9.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://code.qt.io/cgit/pyside/pyside-setup.git | optional Qt runtime modules; dynamic libraries |
| PySide6 Addons | 6.9.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://code.qt.io/cgit/pyside/pyside-setup.git | optional Qt runtime modules; dynamic libraries |
| Shiboken6 | 6.9.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://code.qt.io/cgit/pyside/pyside-setup.git | transitive PySide binding runtime |
| comtypes | 1.4.16 | MIT | https://github.com/enthought/comtypes | transitive Windows capture dependency |
| NumPy | 2.2.6 | BSD-3-Clause | https://numpy.org | optional vision runtime |
| OpenCV contrib Python | 4.10.0.84 | Apache-2.0 | https://github.com/opencv/opencv-python | optional vision runtime; sole owner of the packaged `cv2` namespace |
| PaddleOCR | 3.2.0 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleOCR | optional OCR runtime; no models bundled |
| PaddlePaddle | 3.1.1 | Apache-2.0 | https://github.com/PaddlePaddle/Paddle | optional OCR runtime |
| PaddleX | 3.2.1 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleX | transitive OCR runtime |
| Pillow | 12.3.0 | HPND | https://python-pillow.org | transitive OCR runtime |
| fastText wheel | 0.9.2 | MIT | https://github.com/facebookresearch/fastText | optional local language identification runtime; no model bundled |
| pybind11 | 3.1.0 | BSD-3-Clause | https://github.com/pybind/pybind11 | transitive fastText binding dependency |
| llama-cpp-python | 0.3.19 | MIT | https://github.com/abetlen/llama-cpp-python | optional contextual translation runtime; Windows cp312 x64 wheel SHA-256 `1843b30d90e35296dbd9bd0b2b753b42f0fafa6aec6d2b1c0fff352f801bc89b` |
| llama.cpp | included by llama-cpp-python 0.3.19 | MIT | https://github.com/ggml-org/llama.cpp | native transitive contextual runtime |
| Argos Translate | 1.11.0 | MIT or CC0 | https://github.com/argosopentech/argos-translate | optional installed-package-only fallback runtime; no Argos model package redistributed |
| CTranslate2 | 4.8.1 | MIT | https://github.com/OpenNMT/CTranslate2 | transitive Argos native runtime |
| SentencePiece | 0.2.2 | Apache-2.0 | https://github.com/google/sentencepiece | transitive Argos tokenizer runtime |
| Stanza | 1.10.1 | Apache-2.0 | https://github.com/stanfordnlp/stanza | transitive Argos sentence-boundary runtime |
| spaCy | 3.8.15 | MIT | https://github.com/explosion/spaCy | transitive Argos language runtime |
| PyTorch | 2.13.0 | BSD-3-Clause | https://github.com/pytorch/pytorch | transitive Argos/Stanza runtime |
| diskcache | 5.6.3 | Apache-2.0 | https://github.com/grantjenks/python-diskcache | transitive llama-cpp-python runtime |

Downloadable model payloads are not bundled in the wheel or installer. Explicit setup can acquire
only the following Apache-2.0 Qwen GGUF files; the application verifies the listed byte size and
SHA-256 before activation.

| Model | Upstream revision | Size | SHA-256 | Fixed source |
| --- | --- | ---: | --- | --- |
| Qwen2.5 0.5B Instruct Q4_K_M | `9217f5db79a29953eb74d5343926648285ec7e67` | 491400032 | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF |
| Qwen2.5 1.5B Instruct Q4_K_M | `91cad51170dc346986eccefdc2dd33a9da36ead9` | 1117320736 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF |
| Qwen2.5 3B Instruct Q4_K_M | `7dabda4d13d513e3e842b20f0d435c732f172cbe` | 2104932768 | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` | https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF |

Explicit OCR setup can additionally acquire the Apache-2.0 PaddlePaddle `PP-OCRv5_mobile_det`
revision `0d63e78e2b680928f6b1747d76a08db6e645efb7` and
`cyrillic_PP-OCRv5_mobile_rec` revision `712d2d65556ccc1ea7b5d2bb232b018838b6a3ab`.
The application pins each `config.json`, `inference.json`, `inference.pdiparams`, and `inference.yml`
URL at those revisions and verifies the per-file byte size and SHA-256 recorded in
`vision/model_setup.py` before atomic activation. No OCR model is bundled in the wheel or installer.

The lockfile contains additional transitive development and optional-provider packages; the exact
artifact inventory and complete upstream notice texts remain a release gate. No model payload or
Argos language package is bundled. The built-in reviewed-corpus fallback remains available without
native model packages; user-installed Argos packages retain their own model/data terms.
