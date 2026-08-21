from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.detection.region_calibrator import (
    CalibrationError,
    CalibrationSession,
    CalibrationViewport,
    ResizeHandle,
)
from game_chat_translator.models import ChatRegion


class RegionSelectorUnavailable(RuntimeError):
    pass


def launch_region_selector(
    session: CalibrationSession,
    *,
    retry_capture: Callable[[], bytes] | None = None,
    request_retry: Callable[[Callable[[bytes | None], None]], None] | None = None,
    request_preview: (
        Callable[[RawFrame, Callable[[bool, tuple[str, ...]], None]], None] | None
    ) = None,
    request_save: Callable[[ChatRegion, Callable[[bool], None]], None] | None = None,
    on_finished: Callable[[bool], None] | None = None,
) -> int:
    """Launch the frozen-screenshot clipping UI with a memory-only preview."""
    try:
        from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
        from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
        from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget
    except ImportError as exc:
        raise RegionSelectorUnavailable(
            "Install the pinned UI extra to calibrate visually"
        ) from exc

    existing_application = QApplication.instance()
    application: Any = existing_application or QApplication([])
    target_screen = next(
        (
            screen
            for screen in application.screens()
            if screen.name().casefold() in session.metadata.monitor_id.casefold()
        ),
        application.primaryScreen(),
    )
    if target_screen is None:
        raise RegionSelectorUnavailable("No display is available for calibration")
    available = target_screen.availableGeometry()
    side_panel_width = min(360, max(240, available.width() // 3))
    viewport = CalibrationViewport.fit(
        session.metadata.client_width,
        session.metadata.client_height,
        available.width(),
        available.height(),
        side_panel_width=side_panel_width,
        device_pixel_ratio=target_screen.devicePixelRatio(),
    )

    class RegionSelector(QWidget):  # type: ignore[misc]
        HANDLE_RADIUS = 8
        preview_ready = Signal(int, bool, object)
        retry_ready = Signal(int, object)
        save_ready = Signal(int, bool)

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Select the complete chat region")
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setFixedSize(viewport.view_width + side_panel_width, viewport.view_height)
            self.move(available.topLeft())
            self._image = self._new_image()
            self._mode: str | None = None
            self._handle: ResizeHandle | None = None
            self._last_point = QPoint()
            self._preview_generation = 0
            self._retry_generation = 0
            self._finished_reported = False
            self._save_generation = 0
            self._save_in_progress = False
            self.preview_ready.connect(self._apply_preview)
            self.retry_ready.connect(self._apply_retry)
            self.save_ready.connect(self._apply_save)
            self._create_buttons()
            if session.selection is not None:
                QTimer.singleShot(0, self._request_preview)

        def _new_image(self) -> QImage:
            return QImage(
                session.frozen_bgra,
                session.metadata.client_width,
                session.metadata.client_height,
                QImage.Format.Format_ARGB32,
            ).copy()

        def _create_buttons(self) -> None:
            left = viewport.view_width + 20
            width = side_panel_width - 40
            actions = [
                ("Save", self._save),
                ("Reset", self._reset),
                ("Retry Screenshot", self._retry),
                ("Cancel", self._cancel),
            ]
            for index, (label, callback) in enumerate(actions):
                button = QPushButton(label, self)
                button.setGeometry(left, 102 + index * 38, width, 30)
                button.clicked.connect(callback)
                if label == "Retry Screenshot" and retry_capture is None and request_retry is None:
                    button.setEnabled(False)

        def paintEvent(self, _: Any) -> None:
            painter = QPainter(self)
            image_target = QRect(0, 0, viewport.view_width, viewport.view_height)
            painter.drawImage(image_target, self._image)
            painter.fillRect(image_target, QColor(0, 0, 0, 140))
            panel = QRect(viewport.view_width, 0, side_panel_width, viewport.view_height)
            painter.fillRect(panel, QColor("#16181d"))
            painter.setPen(QColor("#f5f7fa"))
            painter.drawText(
                panel.adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignTop,
                "Chat crop preview\n\nDrag to select • drag inside to move\n"
                "drag corner handles to resize\nArrow keys nudge • Shift+Arrow resizes",
            )
            selection = session.selection
            if selection is None:
                return
            source = QRect(selection.left, selection.top, selection.width, selection.height)
            view = viewport.image_rect_to_view(selection)
            target = QRect(view.left, view.top, view.width, view.height)
            painter.drawImage(target, self._image, source)
            painter.setPen(QPen(QColor("#40c4ff"), 2))
            painter.drawRect(target)
            painter.setBrush(QColor("#40c4ff"))
            for point in self._corners(target).values():
                painter.drawEllipse(point, self.HANDLE_RADIUS // 2, self.HANDLE_RADIUS // 2)
            preview_top = 345 if session.preview_lines else 275
            preview_area = panel.adjusted(20, preview_top, -20, -30)
            scaled = source.size().scaled(preview_area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            preview_target = QRect(preview_area.topLeft(), scaled)
            painter.drawImage(preview_target, self._image, source)
            painter.setPen(QPen(QColor("#40c4ff"), 1))
            painter.drawRect(preview_target)
            if session.preview_has_likely_text is False:
                painter.setPen(QColor("#ffb74d"))
                painter.drawText(
                    panel.adjusted(20, 250, -20, -20),
                    Qt.AlignmentFlag.AlignTop,
                    "No likely chat text detected; Save will ask for confirmation.",
                )
            elif session.preview_lines:
                painter.setPen(QColor("#a5d6a7"))
                painter.drawText(
                    panel.adjusted(20, 245, -20, -20),
                    Qt.AlignmentFlag.AlignTop,
                    "Sample OCR:\n" + "\n".join(session.preview_lines[:3]),
                )

        def mousePressEvent(self, event: QMouseEvent) -> None:
            point = event.position().toPoint()
            if event.button() != Qt.MouseButton.LeftButton or point.x() >= viewport.view_width:
                return
            self._last_point = point
            handle = self._hit_handle(point)
            if handle is not None:
                self._mode = "resize"
                self._handle = handle
            elif self._inside_selection(point):
                self._mode = "move"
            else:
                self._mode = "draw"
                self._handle = None
                session.begin_drag(*viewport.view_to_image(point.x(), point.y()))

        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            point = event.position().toPoint()
            current_image = viewport.view_to_image(point.x(), point.y())
            previous_image = viewport.view_to_image(self._last_point.x(), self._last_point.y())
            dx = current_image[0] - previous_image[0]
            dy = current_image[1] - previous_image[1]
            if self._mode == "draw":
                session.update_drag(*current_image)
            elif self._mode == "move":
                session.move(dx, dy)
            elif self._mode == "resize" and self._handle is not None:
                session.resize(self._handle, dx, dy)
            self._last_point = point
            self.update()

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            if self._mode is None or event.button() != Qt.MouseButton.LeftButton:
                return
            point = event.position().toPoint()
            if self._mode == "draw":
                with suppress(CalibrationError):
                    session.end_drag(*viewport.view_to_image(point.x(), point.y()))
            self._mode = None
            self._handle = None
            self._request_preview()
            self.update()

        def keyPressEvent(self, event: QKeyEvent) -> None:
            key = Qt.Key(event.key())
            if key == Qt.Key.Key_Escape:
                self._cancel()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._save()
                return
            if key == Qt.Key.Key_R:
                self._reset()
                return
            if key == Qt.Key.Key_F5:
                self._retry()
                return
            delta = {
                Qt.Key.Key_Left: QPoint(-1, 0),
                Qt.Key.Key_Right: QPoint(1, 0),
                Qt.Key.Key_Up: QPoint(0, -1),
                Qt.Key.Key_Down: QPoint(0, 1),
            }.get(key)
            if delta is not None and session.selection is not None:
                session.nudge(
                    delta.x(),
                    delta.y(),
                    resize=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._request_preview()
                self.update()

        def _save(self) -> None:
            if self._save_in_progress:
                return
            confirm_no_text = False
            try:
                region = session.prepare_save()
            except CalibrationError as exc:
                if session.preview_has_likely_text is False and session.selection is not None:
                    answer = QMessageBox.question(
                        self,
                        "No chat text detected",
                        "Save this region anyway?",
                    )
                    if answer == QMessageBox.StandardButton.Yes:
                        confirm_no_text = True
                        try:
                            region = session.prepare_save(confirm_no_text=True)
                        except CalibrationError as confirmed_error:
                            QMessageBox.warning(self, "Cannot save selection", str(confirmed_error))
                            return
                    else:
                        return
                else:
                    QMessageBox.warning(self, "Cannot save selection", str(exc))
                    return
            if request_save is None:
                try:
                    session.save(confirm_no_text=confirm_no_text)
                except CalibrationError as exc:
                    QMessageBox.warning(self, "Cannot save selection", str(exc))
                    return
                self._invalidate_preview()
                self.close()
                return
            self._save_in_progress = True
            self._save_generation += 1
            generation = self._save_generation
            try:
                request_save(
                    region,
                    lambda success: self.save_ready.emit(generation, success),
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                self._save_in_progress = False
                QMessageBox.warning(
                    self,
                    "Could not save selection",
                    "Calibration storage is temporarily unavailable.",
                )

        def _apply_save(self, generation: int, success: bool) -> None:
            if generation != self._save_generation or session.saved or session.cancelled:
                return
            self._save_in_progress = False
            if not success:
                QMessageBox.warning(
                    self,
                    "Could not save selection",
                    "Calibration storage is temporarily unavailable.",
                )
                return
            session.complete_save()
            self._invalidate_preview()
            self.close()

        def _reset(self) -> None:
            self._invalidate_preview()
            session.reset()
            self.update()

        def _retry(self) -> None:
            if retry_capture is None and request_retry is None:
                return
            if request_retry is not None:
                self._retry_generation += 1
                retry_generation = self._retry_generation
                request_retry(
                    lambda replacement: self.retry_ready.emit(retry_generation, replacement)
                )
                return
            try:
                assert retry_capture is not None
                replacement = retry_capture()
                self._invalidate_preview()
                session.retry(replacement)
                self._image = self._new_image()
            except (CalibrationError, OSError, RuntimeError) as exc:
                QMessageBox.warning(self, "Could not retry screenshot", str(exc))
            self.update()

        def _apply_retry(self, generation: int, replacement: object) -> None:
            if generation != self._retry_generation or session.saved or session.cancelled:
                return
            if not isinstance(replacement, bytes):
                QMessageBox.warning(
                    self,
                    "Could not retry screenshot",
                    "The game client could not be captured safely.",
                )
                return
            try:
                self._invalidate_preview()
                session.retry(replacement)
                self._image = self._new_image()
            except (CalibrationError, OSError, RuntimeError):
                QMessageBox.warning(
                    self,
                    "Could not retry screenshot",
                    "The replacement screenshot was invalid.",
                )
            self.update()

        def _cancel(self) -> None:
            self._invalidate_preview()
            session.cancel()
            self.close()

        def _request_preview(self) -> None:
            selection = session.selection
            if request_preview is None or selection is None:
                return
            self._preview_generation += 1
            preview_generation = self._preview_generation
            session.set_preview_result(has_likely_text=None)
            frame = RawFrame(
                selection.width,
                selection.height,
                "BGRA",
                session.preview_bgra(),
            )
            try:
                request_preview(
                    frame,
                    lambda likely, lines: self.preview_ready.emit(
                        preview_generation, likely, lines
                    ),
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                session.set_preview_result(has_likely_text=None)
                QMessageBox.warning(
                    self,
                    "OCR preview unavailable",
                    "The OCR preview could not start. The screenshot remains in memory "
                    "so you can retry.",
                )

        def _apply_preview(self, generation: int, likely: bool, lines: object) -> None:
            if generation != self._preview_generation:
                return
            rendered = tuple(str(line) for line in lines) if isinstance(lines, tuple) else ()
            session.set_preview_result(has_likely_text=likely, lines=rendered)
            self.update()

        def _invalidate_preview(self) -> None:
            self._preview_generation += 1

        def closeEvent(self, event: Any) -> None:
            self._invalidate_preview()
            self._retry_generation += 1
            self._save_generation += 1
            if not session.saved and not session.cancelled:
                with suppress(CalibrationError):
                    session.cancel()
            if not self._finished_reported and on_finished is not None:
                self._finished_reported = True
                on_finished(session.saved)
            self._image = QImage()
            selectors = getattr(application, "_gct_region_selectors", [])
            with suppress(ValueError):
                selectors.remove(self)
            event.accept()

        def _inside_selection(self, point: QPoint) -> bool:
            selection = session.selection
            if selection is None:
                return False
            view = viewport.image_rect_to_view(selection)
            return bool(QRect(view.left, view.top, view.width, view.height).contains(point))

        def _hit_handle(self, point: QPoint) -> ResizeHandle | None:
            selection = session.selection
            if selection is None:
                return None
            view = viewport.image_rect_to_view(selection)
            rectangle = QRect(view.left, view.top, view.width, view.height)
            for handle, corner in self._corners(rectangle).items():
                if (corner - point).manhattanLength() <= self.HANDLE_RADIUS * 2:
                    return handle
            return None

        @staticmethod
        def _corners(rectangle: QRect) -> dict[ResizeHandle, QPoint]:
            return {
                ResizeHandle.TOP_LEFT: rectangle.topLeft(),
                ResizeHandle.TOP_RIGHT: rectangle.topRight(),
                ResizeHandle.BOTTOM_LEFT: rectangle.bottomLeft(),
                ResizeHandle.BOTTOM_RIGHT: rectangle.bottomRight(),
            }

    selector = RegionSelector()
    selector.show()
    # Preserve widget lifetime when launched from the already-running tray application.
    selectors = getattr(application, "_gct_region_selectors", [])
    selectors.append(selector)
    application._gct_region_selectors = selectors
    if existing_application is not None:
        return 0
    return int(application.exec())
