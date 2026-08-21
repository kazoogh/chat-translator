from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TranslationRow:
    message_id: str
    speaker: str
    natural_text: str
    source_text: str = ""


class TranslationWindowController(Protocol):
    def translation_geometry_changed(
        self, geometry: tuple[int, int, int, int], display_id: str
    ) -> None: ...


def create_translation_window(
    controller: TranslationWindowController,
    *,
    maximum_rows: int = 50,
) -> object:
    """Create the always-on-top translation view with bounded widget retention."""
    if maximum_rows <= 0:
        raise ValueError("maximum translation rows must be positive")
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QMoveEvent, QResizeEvent
        from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget
    except ImportError as exc:
        raise RuntimeError("Install the pinned UI extra to show translations") from exc

    class TranslationWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("translation-window")
            self.setWindowTitle("Translations")
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.resize(440, 260)
            outer = QVBoxLayout(self)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            self._content = QWidget()
            self._rows = QVBoxLayout(self._content)
            self._rows.addStretch(1)
            self._message_ids: set[str] = set()
            scroll.setWidget(self._content)
            outer.addWidget(scroll)
            self._geometry_timer = QTimer(self)
            self._geometry_timer.setSingleShot(True)
            self._geometry_timer.setInterval(25)
            self._geometry_timer.timeout.connect(self._publish_geometry)

        def append_translation(self, row: TranslationRow) -> None:
            if row.message_id in self._message_ids:
                return
            label = QLabel(f"{row.speaker}: {row.natural_text}")
            label.setObjectName(f"translation-{row.message_id}")
            label.setProperty("message_id", row.message_id)
            label.setWordWrap(True)
            label.setToolTip(row.source_text)
            self._rows.insertWidget(self._rows.count() - 1, label)
            self._message_ids.add(row.message_id)
            while self.message_count > maximum_rows:
                item = self._rows.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    self._message_ids.discard(str(widget.property("message_id")))
                    widget.setParent(None)
                    widget.deleteLater()

        def clear_messages(self) -> None:
            while self.message_count:
                item = self._rows.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            self._message_ids.clear()

        def restore_geometry(self, geometry: tuple[int, int, int, int]) -> None:
            self.setGeometry(*geometry)

        @property
        def message_count(self) -> int:
            return max(0, int(self._rows.count()) - 1)

        def moveEvent(self, event: QMoveEvent) -> None:
            super().moveEvent(event)
            self._geometry_timer.start()

        def resizeEvent(self, event: QResizeEvent) -> None:
            super().resizeEvent(event)
            self._geometry_timer.start()

        def _publish_geometry(self) -> None:
            geometry = self.geometry()
            screen = self.screen()
            display_id = str(screen.name()) if screen is not None and screen.name() else "primary"
            controller.translation_geometry_changed(
                (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                display_id,
            )

    return TranslationWindow()
