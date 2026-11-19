"""Small vector icons drawn with QPainter (no external icon assets needed)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def _pen(painter: QPainter, color: str, width: float = 1.6) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _fill(painter: QPainter, color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def make_icon(name: str, color: str = "#475569", size: int = 20) -> QIcon:
    """Draw one of the bundled glyphs."""

    pixmap, painter = _canvas(size)
    scale = size / 20.0
    painter.scale(scale, scale)
    _pen(painter, color)

    if name == "dashboard":
        _fill(painter, color)
        painter.drawRoundedRect(QRectF(3, 3, 6, 6), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(11, 3, 6, 8), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(3, 11, 6, 6), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(11, 13, 6, 4), 1.6, 1.6)
    elif name == "studio":
        painter.drawLine(QPointF(3, 7), QPointF(3, 3))
        painter.drawLine(QPointF(3, 3), QPointF(7, 3))
        painter.drawLine(QPointF(13, 3), QPointF(17, 3))
        painter.drawLine(QPointF(17, 3), QPointF(17, 7))
        painter.drawLine(QPointF(17, 13), QPointF(17, 17))
        painter.drawLine(QPointF(17, 17), QPointF(13, 17))
        painter.drawLine(QPointF(7, 17), QPointF(3, 17))
        painter.drawLine(QPointF(3, 17), QPointF(3, 13))
        painter.drawRect(QRectF(7, 7, 6, 6))
    elif name == "batch":
        painter.drawRoundedRect(QRectF(6, 3, 11, 8), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(3, 7, 11, 8), 1.6, 1.6)
        painter.drawRoundedRect(QRectF(6, 11, 11, 8), 1.6, 1.6)
    elif name == "profiles":
        painter.drawRoundedRect(QRectF(2.5, 5, 15, 10), 2, 2)
        painter.drawLine(QPointF(5.5, 8.5), QPointF(9, 8.5))
        painter.drawLine(QPointF(5.5, 12), QPointF(11, 12))
        painter.drawEllipse(QPointF(14.5, 10), 2.2, 2.2)
    elif name == "history":
        painter.drawEllipse(QPointF(10, 10), 7, 7)
        painter.drawLine(QPointF(10, 6), QPointF(10, 10))
        painter.drawLine(QPointF(10, 10), QPointF(13, 12))
    elif name == "export":
        painter.drawLine(QPointF(10, 3), QPointF(10, 12))
        painter.drawLine(QPointF(6.5, 8.5), QPointF(10, 12))
        painter.drawLine(QPointF(13.5, 8.5), QPointF(10, 12))
        path = QPainterPath()
        path.moveTo(3, 13)
        path.lineTo(3, 16)
        path.lineTo(17, 16)
        path.lineTo(17, 13)
        painter.drawPath(path)
    elif name == "settings":
        painter.drawEllipse(QPointF(10, 10), 3, 3)
        painter.drawEllipse(QPointF(10, 10), 6.6, 6.6)
        for angle in (0, 45, 90, 135, 180, 225, 270, 315):
            import math

            rad = math.radians(angle)
            x1 = 10 + 6.6 * math.cos(rad)
            y1 = 10 + 6.6 * math.sin(rad)
            x2 = 10 + 8.4 * math.cos(rad)
            y2 = 10 + 8.4 * math.sin(rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif name == "add":
        painter.drawLine(QPointF(10, 4), QPointF(10, 16))
        painter.drawLine(QPointF(4, 10), QPointF(16, 10))
    elif name == "open":
        painter.drawLine(QPointF(2.5, 15.5), QPointF(5.5, 6))
        painter.drawLine(QPointF(5.5, 6), QPointF(16.5, 6))
        painter.drawLine(QPointF(16.5, 6), QPointF(18, 15.5))
        painter.drawLine(QPointF(2.5, 15.5), QPointF(18, 15.5))
    elif name == "save":
        painter.drawRoundedRect(QRectF(3, 3, 14, 14), 2, 2)
        painter.drawLine(QPointF(6, 3), QPointF(6, 8))
        painter.drawLine(QPointF(6, 8), QPointF(14, 8))
        painter.drawRoundedRect(QRectF(6.5, 11, 7, 6), 1, 1)
    elif name == "undo":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 6, 11, 11), 150)
        path.arcTo(QRectF(4, 6, 11, 11), 150, -240)
        painter.drawPath(path)
        painter.drawLine(QPointF(4, 6), QPointF(4, 10))
    elif name == "redo":
        path = QPainterPath()
        path.arcMoveTo(QRectF(5, 6, 11, 11), 30)
        path.arcTo(QRectF(5, 6, 11, 11), 30, 240)
        painter.drawPath(path)
        painter.drawLine(QPointF(16, 6), QPointF(16, 10))
    elif name == "trash":
        painter.drawLine(QPointF(4, 5.5), QPointF(16, 5.5))
        painter.drawLine(QPointF(8, 5.5), QPointF(8, 3.5))
        painter.drawLine(QPointF(8, 3.5), QPointF(12, 3.5))
        painter.drawLine(QPointF(12, 3.5), QPointF(12, 5.5))
        painter.drawRoundedRect(QRectF(5, 5.5, 10, 11), 1.5, 1.5)
    elif name == "copy":
        painter.drawRoundedRect(QRectF(3, 3, 10, 10), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(7, 7, 10, 10), 1.5, 1.5)
    elif name == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 12, 12), 120)
        path.arcTo(QRectF(4, 4, 12, 12), 120, 300)
        painter.drawPath(path)
        painter.drawLine(QPointF(15, 4), QPointF(16, 8))
    elif name == "folder":
        painter.drawRoundedRect(QRectF(2.5, 5, 15, 11), 2, 2)
        painter.drawLine(QPointF(2.5, 8), QPointF(9, 8))
    elif name == "check":
        painter.drawLine(QPointF(4, 10.5), QPointF(8, 14.5))
        painter.drawLine(QPointF(8, 14.5), QPointF(16, 5.5))
    elif name == "close":
        painter.drawLine(QPointF(5, 5), QPointF(15, 15))
        painter.drawLine(QPointF(15, 5), QPointF(5, 15))
    elif name == "zoom_in":
        painter.drawEllipse(QPointF(8.5, 8.5), 5.5, 5.5)
        painter.drawLine(QPointF(12.7, 12.7), QPointF(17, 17))
        painter.drawLine(QPointF(6, 8.5), QPointF(11, 8.5))
        painter.drawLine(QPointF(8.5, 6), QPointF(8.5, 11))
    elif name == "zoom_out":
        painter.drawEllipse(QPointF(8.5, 8.5), 5.5, 5.5)
        painter.drawLine(QPointF(12.7, 12.7), QPointF(17, 17))
        painter.drawLine(QPointF(6, 8.5), QPointF(11, 8.5))
    elif name == "fit":
        painter.drawLine(QPointF(3, 7), QPointF(3, 3))
        painter.drawLine(QPointF(3, 3), QPointF(7, 3))
        painter.drawLine(QPointF(13, 3), QPointF(17, 3))
        painter.drawLine(QPointF(17, 3), QPointF(17, 7))
        painter.drawLine(QPointF(17, 13), QPointF(17, 17))
        painter.drawLine(QPointF(17, 17), QPointF(13, 17))
        painter.drawLine(QPointF(7, 17), QPointF(3, 17))
        painter.drawLine(QPointF(3, 17), QPointF(3, 13))
    elif name == "pdf":
        painter.drawRoundedRect(QRectF(4, 2.5, 12, 15), 2, 2)
        painter.drawLine(QPointF(7, 8), QPointF(13, 8))
        painter.drawLine(QPointF(7, 11), QPointF(13, 11))
        painter.drawLine(QPointF(7, 14), QPointF(11, 14))
    elif name == "warning":
        path = QPainterPath()
        path.moveTo(10, 3)
        path.lineTo(18, 17)
        path.lineTo(2, 17)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(10, 8), QPointF(10, 12))
        painter.drawPoint(QPointF(10, 14.5))
    else:
        painter.drawEllipse(QPointF(10, 10), 6, 6)

    painter.end()
    return QIcon(pixmap)
