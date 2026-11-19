"""Zoomable / pannable image canvas with four draggable document corners."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsView

from core import perspective
from ui.image_utils import bgr_to_pixmap
from .corner_handle import CornerHandle

LABELS = ("TL", "TR", "BR", "BL")
MIN_SCALE = 0.04
MAX_SCALE = 16.0
# Interactive corner limits. The Correction Studio commit path must use the
# same values so a quad accepted by the canvas is never silently rejected on
# commit (which would desync the canvas, the undo stack and the preview).
CANVAS_MIN_AREA = 200.0
CANVAS_MIN_SIDE = 12.0


class ImageCanvas(QGraphicsView):
    cornersChanged = Signal(list)
    cornersCommitted = Signal(list)
    zoomChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ImageCanvas")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._polygon_item: QGraphicsPolygonItem | None = None
        self._handles: list[CornerHandle] = []
        self._selected = 0
        self._image_size = (0, 0)
        self._panning = False
        self._last_pan_point = QPoint()
        self._fit_on_resize = True
        self._loading = False
        # Arrow-key nudges restart this timer; one undo entry is committed
        # after the nudge burst settles instead of one per pixel step.
        self._nudge_timer = QTimer(self)
        self._nudge_timer.setSingleShot(True)
        self._nudge_timer.setInterval(400)
        self._nudge_timer.timeout.connect(self._emit_committed)

    # ------------------------------------------------------------------ data
    def has_image(self) -> bool:
        return self._pixmap_item is not None

    def set_image(self, image: np.ndarray, corners: np.ndarray | None = None) -> None:
        self._loading = True
        self._nudge_timer.stop()
        try:
            self._scene.clear()
            self._pixmap_item = None
            self._handles = []
            self._polygon_item = None

            height, width = image.shape[:2]
            self._image_size = (width, height)
            pixmap = bgr_to_pixmap(image)
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._pixmap_item.setZValue(0)
            self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.setSceneRect(QRectF(0, 0, width, height))

            self._polygon_item = QGraphicsPolygonItem()
            pen = QPen(QColor("#2563EB"))
            pen.setWidthF(1.6)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._polygon_item.setPen(pen)
            self._polygon_item.setBrush(QBrush(QColor(37, 99, 235, 24)))
            self._polygon_item.setZValue(5)
            self._scene.addItem(self._polygon_item)

            points = corners
            if points is None:
                inset_x = width * 0.05
                inset_y = height * 0.05
                points = np.float32(
                    [
                        [inset_x, inset_y],
                        [width - inset_x, inset_y],
                        [width - inset_x, height - inset_y],
                        [inset_x, height - inset_y],
                    ]
                )
            try:
                ordered = perspective.order_points(points)
            except perspective.InvalidQuadrilateral:
                ordered = self._default_quad()

            for index, label in enumerate(LABELS):
                handle = CornerHandle(index, label)
                handle.set_bounds(width, height)
                handle.set_validator(self._validate_handle)
                handle.setPos(QPointF(float(ordered[index][0]), float(ordered[index][1])))
                handle.released.connect(self._on_handle_released)
                handle.moved.connect(self._on_handle_moved)
                handle.setVisible(True)
                self._scene.addItem(handle)
                self._handles.append(handle)

            self._update_polygon()
            self._update_active_handle()
            self.fit_to_view()
        finally:
            # Reset even on failure, otherwise handle dragging stays dead for
            # every image loaded afterwards.
            self._loading = False

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._polygon_item = None
        self._handles = []
        self._image_size = (0, 0)
        self.resetTransform()
        self.viewport().update()

    def corners(self) -> list[list[float]]:
        return [
            [round(handle.pos().x(), 2), round(handle.pos().y(), 2)]
            for handle in self._handles
        ]

    def set_corners(self, corners, quiet: bool = False) -> None:
        if len(self._handles) != 4:
            return
        try:
            ordered = perspective.order_points(corners)
        except perspective.InvalidQuadrilateral:
            return
        self._loading = True
        try:
            for index, handle in enumerate(self._handles):
                handle.set_silent_position(QPointF(float(ordered[index][0]), float(ordered[index][1])))
        finally:
            self._loading = False
        self._update_polygon()
        self._update_active_handle()
        if not quiet:
            self.cornersChanged.emit(self.corners())

    def _default_quad(self) -> np.ndarray:
        width, height = self._image_size
        return np.float32(
            [[0, 0], [max(0, width - 1), 0], [max(0, width - 1), max(0, height - 1)], [0, max(0, height - 1)]]
        )

    # -------------------------------------------------------------- editing
    def _validate_handle(self, index: int, point: QPointF) -> QPointF | None:
        """Reject moves that would create a crossed or concave quadrilateral.

        Bulk updates (``set_corners``) bypass validation: applying four new
        corners one at a time is transiently invalid, and validating partway
        through would leave the outline half-updated.
        """

        if self._loading:
            return point
        if len(self._handles) != 4:
            return point
        proposed = [[handle.pos().x(), handle.pos().y()] for handle in self._handles]
        proposed[index] = [point.x(), point.y()]
        if perspective.is_valid_quad(
            proposed, min_area=CANVAS_MIN_AREA, min_side=CANVAS_MIN_SIDE
        ):
            return point
        return None

    def _update_polygon(self) -> None:
        if self._polygon_item is None or len(self._handles) != 4:
            return
        polygon = QPolygonF([handle.pos() for handle in self._handles])
        self._polygon_item.setPolygon(polygon)

    def _on_handle_released(self, _index: int) -> None:
        self._update_polygon()
        self._nudge_timer.stop()
        self.cornersCommitted.emit(self.corners())

    def _emit_committed(self) -> None:
        """Commit the accumulated nudge edits as a single undo entry."""
        if not self._handles:
            return
        self._update_polygon()
        self.cornersCommitted.emit(self.corners())

    def _on_handle_moved(self, _index: int, _point: QPointF) -> None:
        # Keep the outline and coordinate feedback accurate while dragging.
        if self._loading:
            return
        self._update_polygon()
        self.cornersChanged.emit(self.corners())

    # -------------------------------------------------------------- view ops
    def fit_to_view(self) -> None:
        if self._pixmap_item is None:
            return
        rect = self.sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)
        # fitInView can exceed the interactive zoom limit (a small image in a
        # large viewport); clamp so zoom-in does not appear dead afterwards.
        current = self.transform().m11()
        if current > MAX_SCALE:
            factor = MAX_SCALE / current
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.scale(factor, factor)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_on_resize = True
        self.zoomChanged.emit(self.zoom_percent())

    def actual_size(self) -> None:
        self.resetTransform()
        self._fit_on_resize = False
        self.zoomChanged.emit(self.zoom_percent())

    def zoom_in(self) -> None:
        self._apply_zoom(1.2)

    def zoom_out(self) -> None:
        self._apply_zoom(1 / 1.2)

    def _apply_zoom(self, factor: float, anchor_under_mouse: bool = False) -> None:
        if self._pixmap_item is None:
            return
        current = self.transform().m11()
        # Clamp to the limits instead of rejecting, so wheel/button zoom at a
        # limit still moves to the boundary rather than doing nothing.
        target = max(MIN_SCALE, min(MAX_SCALE, current * factor))
        if abs(target - current) < 1e-6:
            return
        # Button/zoom-box calls run with the cursor outside the viewport; the
        # under-mouse anchor would pan the view to an off-screen scene point.
        anchor = (
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if anchor_under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.setTransformationAnchor(anchor)
        try:
            self.scale(target / current, target / current)
        finally:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_on_resize = False
        self.zoomChanged.emit(self.zoom_percent())

    def zoom_percent(self) -> int:
        return int(round(self.transform().m11() * 100))

    def set_zoom_percent(self, percent: int) -> None:
        if self._pixmap_item is None:
            return
        current = self.transform().m11()
        scale = max(MIN_SCALE, min(MAX_SCALE, percent / 100.0))
        if abs(scale - current) < 1e-6:
            return
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        try:
            self.resetTransform()
            self.scale(scale, scale)
        finally:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_on_resize = False
        self.zoomChanged.emit(self.zoom_percent())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_on_resize and self._pixmap_item is not None:
            self.fit_to_view()

    def wheelEvent(self, event) -> None:
        if self._pixmap_item is None:
            return super().wheelEvent(event)
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._apply_zoom(1.15 if delta > 0 else 1 / 1.15, anchor_under_mouse=True)
        event.accept()

    # ------------------------------------------------------------ mouse/keys
    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, CornerHandle):
            self._selected = item.index
            self._update_active_handle()
            self.setFocus()
            super().mousePressEvent(event)
            return
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = True
            self._last_pan_point = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            current = event.position().toPoint()
            delta = current - self._last_pan_point
            self._last_pan_point = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._fit_on_resize = False
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click to zoom to the selected corner or fit to view."""
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, CornerHandle):
            # Zoom to the selected corner handle
            self._selected = item.index
            self._update_active_handle()
            self._zoom_to_handle(item)
            event.accept()
            return
        # Double-click empty area: fit to view
        self.fit_to_view()
        event.accept()

    def _zoom_to_handle(self, handle: CornerHandle) -> None:
        """Zoom and center the view on a specific corner handle."""
        if self._pixmap_item is None:
            return
        # Center the view on the handle
        self.centerOn(handle.scenePos())
        # Zoom in to a comfortable level (200%)
        target_zoom = 2.0
        current_zoom = self.transform().m11()
        if abs(target_zoom - current_zoom) > 0.01:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            try:
                self.scale(target_zoom / current_zoom, target_zoom / current_zoom)
            finally:
                self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self._fit_on_resize = False
            self.zoomChanged.emit(self.zoom_percent())

    def _update_active_handle(self) -> None:
        """Update the active state of all handles based on _selected."""
        for i, handle in enumerate(self._handles):
            handle.set_active(i == self._selected)

    def keyPressEvent(self, event) -> None:
        if not self._handles:
            return super().keyPressEvent(event)
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        deltas = {
            int(Qt.Key.Key_Left): (-step, 0.0),
            int(Qt.Key.Key_Right): (step, 0.0),
            int(Qt.Key.Key_Up): (0.0, -step),
            int(Qt.Key.Key_Down): (0.0, step),
        }
        key = int(event.key())
        if key in deltas:
            handle = self._handles[self._selected]
            dx, dy = deltas[key]
            target = QPointF(handle.pos().x() + dx, handle.pos().y() + dy)
            validated = self._validate_handle(self._selected, target)
            if validated is not None:
                handle.set_silent_position(validated)
                self._update_polygon()
                self.cornersChanged.emit(self.corners())
                self._nudge_timer.start()
            event.accept()
            return
        if key in (int(Qt.Key.Key_1), int(Qt.Key.Key_2), int(Qt.Key.Key_3), int(Qt.Key.Key_4)):
            self._selected = key - int(Qt.Key.Key_1)
            self._update_active_handle()
            event.accept()
            return
        super().keyPressEvent(event)

    # -------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap_item is not None:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#CBD5E1")))
        font = QFont(painter.font())
        font.setPixelSize(13)
        painter.setFont(font)
        painter.drawText(
            self.viewport().rect(),
            Qt.AlignmentFlag.AlignCenter,
            "Open a photo of your document to start\n"
            "Drag or paste an image here, or use Open image",
        )
        painter.end()
