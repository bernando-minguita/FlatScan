"""Non-blocking toast messages anchored to the top-right of the window."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QObject, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.icons import make_icon

_KINDS = {
    "info": ("ToastInfo", "#334155"),
    "success": ("ToastSuccess", "#15803D"),
    "warning": ("ToastWarning", "#B45309"),
    "error": ("ToastError", "#B91C1C"),
}


class NotificationHost(QWidget):
    """Transparent overlay that owns a single reusable toast."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._toast: QFrame | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_toast)
        parent.installEventFilter(self)
        # The host widget is sized to the toast itself, not to the whole
        # window: a full-window overlay would swallow every click, scroll and
        # drag for the lifetime of the toast.
        self.setGeometry(0, 0, 0, 0)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._parent and event.type() == QEvent.Type.Resize:
            self._reposition()
        return super().eventFilter(watched, event)

    def show_message(self, text: str, kind: str = "info", timeout: int = 4200) -> None:
        name, color = _KINDS.get(kind, _KINDS["info"])
        if self._toast is not None:
            self._toast.deleteLater()
        frame = QFrame(self)
        frame.setObjectName(name)
        frame.setMaximumWidth(440)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 9, 8, 9)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(make_icon("check" if kind == "success" else "warning", color, 16).pixmap(16, 16))
        message = QLabel(text)
        message.setWordWrap(True)
        message.setStyleSheet("background: transparent;")
        close = QPushButton()
        close.setObjectName("Ghost")
        close.setIcon(make_icon("close", "#64748B", 12))
        close.setFixedSize(22, 22)
        close.setToolTip("Dismiss")
        close.clicked.connect(self.hide_toast)

        layout.addWidget(icon)
        layout.addWidget(message, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._toast = frame
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(timeout)

    def _reposition(self) -> None:
        if self._toast is None:
            return
        self._toast.adjustSize()
        width = min(self._toast.sizeHint().width(), 440)
        self._toast.setFixedWidth(max(260, width))
        self._toast.adjustSize()
        # The host covers exactly the toast area; the toast sits at its origin.
        self.setGeometry(self._host_rect())
        self._toast.move(0, 0)
        self._toast.raise_()

    def _host_rect(self):
        size = self._toast.size()
        x = max(12, self._parent.width() - size.width() - 22)
        return QRect(x, 18, size.width(), size.height())

    def hide_toast(self) -> None:
        self._timer.stop()
        if self._toast is not None:
            self._toast.deleteLater()
            self._toast = None
        self.hide()
