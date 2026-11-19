"""Compact zoom controls used by the correction canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui.icons import make_icon


class ZoomControls(QWidget):
    zoomInRequested = Signal()
    zoomOutRequested = Signal()
    fitRequested = Signal()
    actualSizeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.zoom_out = QPushButton()
        self.zoom_out.setObjectName("IconButton")
        self.zoom_out.setIcon(make_icon("zoom_out", "#475569", 16))
        self.zoom_out.setToolTip("Zoom out (mouse wheel)")
        self.zoom_out.clicked.connect(self.zoomOutRequested.emit)

        self.percent = QLabel("100%")
        self.percent.setObjectName("Tiny")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.percent.setMinimumWidth(44)

        self.zoom_in = QPushButton()
        self.zoom_in.setObjectName("IconButton")
        self.zoom_in.setIcon(make_icon("zoom_in", "#475569", 16))
        self.zoom_in.setToolTip("Zoom in (mouse wheel)")
        self.zoom_in.clicked.connect(self.zoomInRequested.emit)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setObjectName("Ghost")
        self.fit_button.setToolTip("Fit the document to the view")
        self.fit_button.clicked.connect(self.fitRequested.emit)

        self.actual_button = QPushButton("100%")
        self.actual_button.setObjectName("Ghost")
        self.actual_button.setToolTip("Show the image at one screen pixel per image pixel")
        self.actual_button.clicked.connect(self.actualSizeRequested.emit)

        layout.addWidget(self.zoom_out)
        layout.addWidget(self.percent)
        layout.addWidget(self.zoom_in)
        layout.addSpacing(6)
        layout.addWidget(self.fit_button)
        layout.addWidget(self.actual_button)

    def set_zoom(self, percent: int) -> None:
        self.percent.setText(f"{max(1, percent)}%")
