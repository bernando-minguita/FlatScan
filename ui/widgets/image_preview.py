"""Scaled image preview with an optional draggable before/after split."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ui.image_utils import bgr_to_pixmap
from ui.styles.theme import DARK, LIGHT, THEMES


def _current_theme_colors() -> dict:
    """Return the colour tokens for the currently active theme."""
    app = QApplication.instance()
    theme_name = app.property("flatscan_theme") if app else "light"
    return THEMES.get((theme_name or "light").lower(), LIGHT)


class ImagePreview(QWidget):
    """Displays a corrected image; optionally compares it with the warp result."""

    compareToggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._after: QPixmap | None = None
        self._before: QPixmap | None = None
        self._compare = False
        self._split = 0.5
        self._empty_text = "The corrected document will appear here."
        self._dragging = False
        self.setMinimumSize(240, 160)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ data
    def set_image(self, image: np.ndarray | None) -> None:
        self._after = bgr_to_pixmap(image) if image is not None and image.size else None
        self.update()

    def set_before(self, image: np.ndarray | None) -> None:
        self._before = bgr_to_pixmap(image) if image is not None and image.size else None
        self.update()

    def set_compare(self, enabled: bool) -> None:
        self._compare = bool(enabled)
        self.update()

    def is_comparing(self) -> bool:
        return self._compare

    def clear(self) -> None:
        self._after = None
        self._before = None
        self.update()

    def has_image(self) -> bool:
        return self._after is not None

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.update()

    # --------------------------------------------------------------- painting
    def _target_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        pixmap = self._after or self._before
        if pixmap is None or area.width() <= 0 or area.height() <= 0:
            return area
        ratio = min(area.width() / pixmap.width(), area.height() / pixmap.height())
        width = pixmap.width() * ratio
        height = pixmap.height() * ratio
        return QRectF(
            area.center().x() - width / 2.0,
            area.center().y() - height / 2.0,
            width,
            height,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(_current_theme_colors()["surface"]))

        rect = self._target_rect()
        if self._after is None and self._before is None:
            colors = _current_theme_colors()
            pen = QPen(QColor(colors["border"]))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(12, 12, -12, -12), 10, 10)
            painter.setPen(QColor(colors["text_muted"]))
            font = QFont(painter.font())
            font.setPixelSize(13)
            painter.setFont(font)
            painter.drawText(
                self.rect(),
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                self._empty_text,
            )
            painter.end()
            return

        if self._compare and self._before is not None and self._after is not None:
            split_x = rect.left() + rect.width() * self._split
            painter.save()
            painter.setClipRect(QRectF(rect.left(), rect.top(), split_x - rect.left(), rect.height()))
            painter.drawPixmap(rect, self._before, QRectF(self._before.rect()))
            painter.restore()
            painter.save()
            painter.setClipRect(QRectF(split_x, rect.top(), rect.right() - split_x, rect.height()))
            painter.drawPixmap(rect, self._after, QRectF(self._after.rect()))
            painter.restore()

            colors = _current_theme_colors()
            accent = QColor(colors["accent"])
            painter.setPen(QPen(accent, 2))
            painter.drawLine(QPointF(split_x, rect.top()), QPointF(split_x, rect.bottom()))
            handle = QRectF(split_x - 13, rect.center().y() - 16, 26, 32)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(accent, 1.5))
            painter.drawRoundedRect(handle, 7, 7)
            painter.setPen(QPen(accent, 2))
            painter.drawLine(QPointF(split_x - 5, rect.center().y() - 3), QPointF(split_x - 5, rect.center().y() + 3))
            painter.drawLine(QPointF(split_x + 5, rect.center().y() - 3), QPointF(split_x + 5, rect.center().y() + 3))

            self._draw_tag(painter, rect.topLeft() + QPointF(10, 10), "BEFORE")
            self._draw_tag(painter, rect.topRight() + QPointF(-64, 10), "AFTER")
        else:
            painter.drawPixmap(rect, self._after or self._before, QRectF((self._after or self._before).rect()))

        if self._after is not None:
            label = f"{self._after.width()} × {self._after.height()} px"
            colors = _current_theme_colors()
            painter.setPen(QColor(colors["text_muted"]))
            font = QFont(painter.font())
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(6, 0, -6, -6),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                label,
            )
        painter.end()

    @staticmethod
    def _draw_tag(painter: QPainter, top_left: QPointF, text: str) -> None:
        colors = _current_theme_colors()
        rect = QRectF(top_left.x(), top_left.y(), 54, 20)
        painter.setBrush(QColor(colors["surface"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont(painter.font())
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        if self._compare and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_split(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._update_split(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _update_split(self, x: float) -> None:
        rect = self._target_rect()
        if rect.width() <= 0:
            return
        self._split = max(0.02, min(0.98, (x - rect.left()) / rect.width()))
        self.update()
