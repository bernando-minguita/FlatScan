"""A draggable, labelled corner handle for the perspective editor."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject

ACCENT = QColor("#2563EB")
ACTIVE_ACCENT = QColor("#F59E0B")  # Amber for active selection


class CornerHandle(QGraphicsObject):
    """Circular handle that always keeps a constant on-screen size.

    ``QGraphicsObject`` (rather than ``QGraphicsEllipseItem``) is used so the
    handle can emit Qt signals; plain graphics items are not QObjects.
    """

    released = Signal(int)
    moved = Signal(int, QPointF)

    def __init__(self, index: int, label: str, radius: float = 8.0, parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.label = label
        self.radius = radius
        self._guard = False
        self._bounds: tuple[int, int] = (0, 0)
        self._validate = None
        self._press_position: QPointF | None = None
        self._active = False

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)
        self.setToolTip(f"{label} corner — drag, or use the arrow keys")

    # -------------------------------------------------------------- geometry
    def boundingRect(self) -> QRectF:
        radius = self.radius + 3.0  # Extra space for active ring
        return QRectF(-radius, -radius, radius * 2, radius * 2)

    def shape(self):
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addEllipse(self.boundingRect())
        return path

    # ------------------------------------------------------------- behaviour
    def set_bounds(self, width: int, height: int) -> None:
        self._bounds = (max(1, width), max(1, height))

    def set_validator(self, callback) -> None:
        """``callback(index, QPointF) -> QPointF | None`` returns the allowed point."""

        self._validate = callback

    def set_silent_position(self, point: QPointF) -> None:
        self._guard = True
        self.setPos(point)
        self._guard = False

    def set_active(self, active: bool) -> None:
        """Set the active (keyboard-selected) state."""
        if self._active != active:
            self._active = active
            self.update()

    def is_active(self) -> bool:
        return self._active

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            point = QPointF(value)
            width, height = self._bounds
            point.setX(min(max(point.x(), 0.0), float(max(0, width - 1))))
            point.setY(min(max(point.y(), 0.0), float(max(0, height - 1))))
            if self._validate is not None:
                allowed = self._validate(self.index, point)
                if allowed is None:
                    return self.pos()
                return allowed
            return point
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._guard:
            self.moved.emit(self.index, self.pos())
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.update()
        if self._guard:
            return
        if self._press_position is not None and self.pos() == self._press_position:
            # A plain click without movement: no commit, no re-render.
            self._press_position = None
            return
        self._press_position = None
        self.released.emit(self.index)

    def hoverEnterEvent(self, event) -> None:
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.update()
        super().hoverLeaveEvent(event)

    # -------------------------------------------------------------- painting
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hovering = self.isUnderMouse()
        radius = self.radius + (1.0 if hovering else 0.0)
        
        # Draw active ring behind the handle
        if self._active:
            active_radius = radius + 4.0
            painter.setPen(QPen(ACTIVE_ACCENT, 2.0))
            painter.setBrush(QColor(245, 158, 11, 40))  # Semi-transparent amber
            painter.drawEllipse(QRectF(-active_radius, -active_radius, active_radius * 2, active_radius * 2))
        
        painter.setPen(QPen(QColor("#FFFFFF"), 2.4))
        painter.setBrush(ACTIVE_ACCENT if self._active else (ACCENT if not hovering else QColor("#1D4ED8")))
        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))

        font = QFont(painter.font())
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            QRectF(-radius, -radius, radius * 2, radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            self.label,
        )
