from __future__ import annotations

from pathlib import Path

from game_chat_translator.detection.game_detector import ProfileResolver
from game_chat_translator.models import Bounds, WindowIdentity
from game_chat_translator.profiles.loader import ProfileRegistry

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def window(
    *, executable: str = "javaw.exe", title: str = "Minecraft 1.21", window_class: str = "LWJGL"
) -> WindowIdentity:
    return WindowIdentity(
        process_id=42,
        executable=executable,
        title=title,
        window_class=window_class,
        client_bounds=Bounds(left=-1920, top=0, width=1920, height=1080),
        monitor_id="left",
        dpi=144,
    )


def test_matcher_debounces_and_uses_title_for_generic_java_host() -> None:
    clock = FakeClock()
    profiles = ProfileRegistry(ROOT / "profiles").load_all()
    resolver = ProfileResolver(profiles, debounce_seconds=1.2, clock=clock)

    first = resolver.resolve(window())
    assert first.stable is False
    assert first.should_pause is True
    clock.now = 1.19
    assert resolver.resolve(window()).stable is False
    clock.now = 1.2
    resolved = resolver.resolve(window())
    assert resolved.profile_id == "minecraft.java"
    assert resolved.confidence == 1.0


def test_unknown_or_minimized_window_pauses_without_history() -> None:
    profiles = ProfileRegistry(ROOT / "profiles").load_all()
    resolver = ProfileResolver(profiles, debounce_seconds=0)
    unknown = window(executable="notes.exe", title="private unrelated title", window_class="Editor")
    assert resolver.resolve(unknown).should_pause is True
    minimized = window().model_copy(update={"minimized": True})
    assert resolver.resolve(minimized).should_pause is True


def test_manual_pin_has_immediate_precedence() -> None:
    profiles = ProfileRegistry(ROOT / "profiles").load_all()
    resolver = ProfileResolver(profiles)
    resolver.pin("generic.default")
    result = resolver.resolve(None)
    assert result.profile_id == "generic.default"
    assert result.pinned is True
    assert result.should_pause is False


def test_stalzone_title_foundation_resolves_without_unverified_executable() -> None:
    profiles = ProfileRegistry(ROOT / "profiles").load_all()
    resolver = ProfileResolver(profiles, debounce_seconds=0)
    candidate = window(executable="unknown.exe", title="STALZONE", window_class="UnrealWindow")
    resolver.resolve(candidate)
    assert resolver.resolve(candidate).profile_id == "stalzone.default"


def test_cross_game_switch_pauses_until_new_window_is_stable() -> None:
    clock = FakeClock()
    profiles = ProfileRegistry(ROOT / "profiles").load_all()
    resolver = ProfileResolver(profiles, debounce_seconds=1.0, clock=clock)
    minecraft = window()
    resolver.resolve(minecraft)
    clock.now = 1.0
    assert resolver.resolve(minecraft).profile_id == "minecraft.java"

    stalzone = window(
        executable="unknown.exe", title="STALZONE", window_class="UnrealWindow"
    ).model_copy(update={"process_id": 84})
    switching = resolver.resolve(stalzone)
    assert switching.profile_id is None
    assert switching.should_pause is True
    clock.now = 2.0
    assert resolver.resolve(stalzone).profile_id == "stalzone.default"
