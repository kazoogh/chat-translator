from __future__ import annotations

import re
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
verify = cast(
    Callable[[Path], None],
    runpy.run_path(ROOT / "scripts" / "verify_release_contents.py")["verify"],
)


def test_pyinstaller_spec_collects_required_local_runtime_boundaries() -> None:
    spec = (ROOT / "packaging" / "GameChatTranslator.spec").read_text(encoding="utf-8")
    for required in (
        "PySide6",
        "paddleocr",
        "paddle",
        "cv2",
        "faster_whisper",
        "ctranslate2",
        "llama_cpp",
        "sounddevice",
        "win32com",
        "game_chat_translator/resources/profiles",
        "game_chat_translator/resources/data",
    ):
        assert required in spec
    assert "console=False" in spec


def test_inno_installer_is_per_user_x64_upgradeable_and_opt_in_at_startup() -> None:
    script = (ROOT / "installer" / "GameChatTranslator.iss").read_text(encoding="utf-8")
    assert "B63B0DAA-77DF-4C81-A157-655453368AC6" in script
    assert "PrivilegesRequired=lowest" in script
    assert "ArchitecturesAllowed=x64compatible" in script
    assert "MinVersion=10.0.17763" in script
    assert 'Name: "startup"' in script and "Flags: unchecked" in script
    assert "DelTree(ExpandConstant('{localappdata}\\GameChatTranslator')" in script
    assert "HasCommandLineParameter('/REMOVEUSERDATA')" in script
    assert "not UninstallSilent" in script
    assert "GameChatTranslator-Setup-x64" in script


def test_build_script_checks_frozen_executable_before_installer_and_hashes_exact_asset() -> None:
    script = (ROOT / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
    frozen_smoke = script.index("Invoke-FrozenSmoke '--packaging-smoke'")
    runtime_smoke = script.index("Invoke-FrozenSmoke '--frozen-runtime-smoke'")
    compiler = script.index("& $iscc")
    checksum = script.index("Get-FileHash -LiteralPath $installer")
    assert frozen_smoke < runtime_smoke < compiler < checksum


def test_release_content_inspection_rejects_models_private_audio_and_dev_packages(
    tmp_path: Path,
) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "GameChatTranslator.exe").write_bytes(b"release")
    verify(clean)

    forbidden = tmp_path / "forbidden" / "pytest"
    forbidden.mkdir(parents=True)
    (forbidden / "model.bin").write_bytes(b"private")
    with pytest.raises(RuntimeError, match="forbidden release payloads"):
        verify(tmp_path / "forbidden")

    asio = tmp_path / "asio"
    asio.mkdir()
    (asio / "libportaudio64bit-asio.dll").write_bytes(b"unsupported")
    with pytest.raises(RuntimeError, match="forbidden release payloads"):
        verify(asio)

    (asio / "cudnn64_9.dll").write_bytes(b"unused GPU runtime")
    with pytest.raises(RuntimeError, match="forbidden release payloads"):
        verify(asio)


def test_release_workflow_is_pinned_and_tests_before_packaging() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(encoding="utf-8")
    actions = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", workflow)
    assert actions and all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in actions)
    assert "package:\n    needs: test" in workflow
    assert "release:\n    if:" in workflow and "needs: package" in workflow
    assert "continue-on-error" not in workflow
    assert "release-assets/installer/GameChatTranslator-Setup-x64.exe" in workflow
    assert (
        "release-assets/Game Chat Translator/GameChatTranslator/licenses/runtime/"
        "runtime-artifact-inventory.json"
    ) in workflow
