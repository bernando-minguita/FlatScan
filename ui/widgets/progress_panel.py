"""Inline progress indicator with an optional cancel action."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class ProgressPanel(QWidget):
    cancelRequested = Signal()

    def __init__(self, cancel_text: str = "Cancel", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        self.label = QLabel("Ready")
        self.label.setObjectName("Hint")
        self.detail = QLabel("")
        self.detail.setObjectName("Tiny")
        self.detail.setVisible(False)
        text_column.addWidget(self.label)
        text_column.addWidget(self.detail)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setMinimumWidth(140)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)

        self.cancel_button = QPushButton(cancel_text)
        self.cancel_button.setObjectName("Ghost")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)

        layout.addLayout(text_column, 1)
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.cancel_button)

    def set_idle(self, text: str = "Ready", detail: str = "") -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.label.setText(text)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.cancel_button.setVisible(False)

    def set_busy(self, text: str = "Working…", detail: str = "", cancellable: bool = False) -> None:
        self.bar.setRange(0, 0)
        self.label.setText(text)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.cancel_button.setVisible(cancellable)

    def set_progress(self, value: int, maximum: int, text: str = "", detail: str = "") -> None:
        self.bar.setRange(0, max(1, maximum))
        self.bar.setValue(min(value, maximum))
        if text:
            self.label.setText(text)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))

    def set_complete(self, text: str, detail: str = "", problem: bool = False) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if not problem else 0)
        self.label.setText(text)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.cancel_button.setVisible(False)
