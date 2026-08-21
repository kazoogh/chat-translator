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
| PySide6 / Qt | 6.9.1 | LGPL-3.0-only (selected modules) | https://www.qt.io | optional desktop UI; dynamic libraries and notices must ship |
| comtypes | 1.4.16 | MIT | https://github.com/enthought/comtypes | transitive Windows capture dependency |
| NumPy | 2.2.6 | BSD-3-Clause | https://numpy.org | optional vision runtime |
| OpenCV Python / contrib | 4.10.0.84 | Apache-2.0 | https://github.com/opencv/opencv-python | optional capture/vision runtime; matched versions share the `cv2` namespace |
| PaddleOCR | 3.2.0 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleOCR | optional OCR runtime; no models bundled |
| PaddlePaddle | 3.1.1 | Apache-2.0 | https://github.com/PaddlePaddle/Paddle | optional OCR runtime |
| PaddleX | 3.2.1 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleX | transitive OCR runtime |
| Pillow | 12.3.0 | HPND | https://python-pillow.org | transitive OCR runtime |
| fastText wheel | 0.9.2 | MIT | https://github.com/facebookresearch/fastText | optional local language identification runtime; no model bundled |
| pybind11 | 3.1.0 | BSD-3-Clause | https://github.com/pybind/pybind11 | transitive fastText binding dependency |

The lockfile contains additional transitive development and optional-provider packages; the exact
artifact inventory and complete upstream notice texts remain a release gate. No model payload is
bundled at this stage. Each downloadable model requires separate source, license, size, and SHA-256
metadata before it can appear in the allowlist.
