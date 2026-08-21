from __future__ import annotations

from typing import Protocol


class TrayController(Protocol):
    def toggle_pause(self) -> None: ...

    def toggle_mute(self) -> None: ...

    def show_dashboard(self) -> None: ...

    def quit_application(self) -> None: ...


def create_tray_icon(
    controller: TrayController,
    *,
    tooltip: str = "Game Chat Translator",
    icon_path: str | None = None,
) -> object:
    """Create tray actions; lifecycle and application shutdown remain controller-owned."""
    try:
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon
    except ImportError as exc:
        raise RuntimeError("Install the pinned UI extra to use the system tray") from exc

    icon = QIcon(icon_path) if icon_path is not None else QIcon.fromTheme("applications-multimedia")
    if icon.isNull():
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    class RuntimeTrayIcon(QSystemTrayIcon):
        def __init__(self) -> None:
            super().__init__(icon)
            self.action_by_label: dict[str, QAction] = {}

        def set_runtime_state(
            self, *, profile_id: str, calibrated: bool, paused: bool, muted: bool
        ) -> None:
            state = "Paused" if paused else "Monitoring"
            calibration = "calibrated" if calibrated else "needs calibration"
            self.setToolTip(f"Game Chat Translator — {profile_id} — {state} — {calibration}")
            pause_action = self.action_by_label["Pause / Resume"]
            mute_action = self.action_by_label["Mute / Unmute"]
            pause_action.setText("Resume Monitoring" if paused else "Pause Monitoring")
            mute_action.setText("Unmute Speech" if muted else "Mute Speech")
            pause_action.setCheckable(True)
            pause_action.setChecked(paused)
            mute_action.setCheckable(True)
            mute_action.setChecked(muted)

    tray = RuntimeTrayIcon()
    tray.setObjectName("tray-icon")
    tray.setToolTip(tooltip)
    menu = QMenu()
    actions = (
        ("Pause / Resume", controller.toggle_pause),
        ("Mute / Unmute", controller.toggle_mute),
        ("Open Dashboard", controller.show_dashboard),
        ("Quit", controller.quit_application),
    )
    for label, callback in actions:
        action = QAction(label, menu)
        action.setObjectName("tray-" + label.casefold().replace(" ", "-"))
        action.triggered.connect(callback)
        menu.addAction(action)
        tray.action_by_label[label] = action
        if label == "Mute / Unmute":
            menu.addSeparator()
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: controller.show_dashboard()
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick
        else None
    )

    return tray
