from __future__ import annotations

from game_chat_translator.detection.layout_resolver import LayoutResolver, normalized_to_screen
from game_chat_translator.models import Bounds, ChatRegion, WindowIdentity


def calibration() -> ChatRegion:
    return ChatRegion(
        x=0.1,
        y=0.75,
        width=0.5,
        height=0.2,
        layout_id="default",
        reference_client_width=1920,
        reference_client_height=1080,
        reference_dpi=96,
    )


def test_normalized_region_tracks_negative_origin_move_and_resize() -> None:
    region = normalized_to_screen(
        calibration(), Bounds(left=-2560, top=100, width=2560, height=1440)
    )
    assert region.left == -2304
    assert region.top == 1180
    assert region.width == 1280
    assert region.height == 288


def test_layout_resolver_pauses_for_minimized_or_missing_calibration() -> None:
    window = WindowIdentity(
        process_id=1,
        executable="game.exe",
        title="Game",
        window_class="GameWindow",
        client_bounds=Bounds(left=0, top=0, width=1920, height=1080),
        monitor_id="primary",
        dpi=96,
        minimized=True,
    )
    resolver = LayoutResolver()
    assert resolver.resolve(calibration(), window) is None
    assert resolver.resolve(None, window.model_copy(update={"minimized": False})) is None


def test_incompatible_ultrawide_or_dpi_requests_new_calibration() -> None:
    base = WindowIdentity(
        process_id=1,
        executable="game.exe",
        title="Game",
        window_class="GameWindow",
        client_bounds=Bounds(left=0, top=0, width=1920, height=1080),
        monitor_id="primary",
        dpi=96,
    )
    resolver = LayoutResolver()
    ultrawide = base.model_copy(
        update={"client_bounds": Bounds(left=0, top=0, width=3440, height=1440)}
    )
    high_dpi = base.model_copy(update={"dpi": 192})
    proportional = base.model_copy(
        update={"client_bounds": Bounds(left=100, top=50, width=2560, height=1440)}
    )
    assert resolver.resolve(calibration(), ultrawide) is None
    assert resolver.resolve(calibration(), high_dpi) is None
    assert resolver.resolve(calibration(), proportional) is not None
