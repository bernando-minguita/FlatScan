"""Dashboard with processing statistics, quick actions and recent work."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.context import AppContext
from ui.icons import make_icon


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(10)
    return frame, layout


class StatCard(QFrame):
    clicked = Signal()

    def __init__(self, label: str, icon_name: str, accent: str = "#2563EB", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        top = QHBoxLayout()
        caption = QLabel(label.upper())
        caption.setObjectName("StatLabel")
        icon = QLabel()
        icon.setPixmap(make_icon(icon_name, accent, 18).pixmap(18, 18))
        top.addWidget(caption)
        top.addStretch(1)
        top.addWidget(icon)
        self.value = QLabel("0")
        self.value.setObjectName("StatValue")
        layout.addLayout(top)
        layout.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DashboardPage(QWidget):
    newCorrectionRequested = Signal()
    batchRequested = Signal()
    openProjectRequested = Signal()
    profilesRequested = Signal()
    recordRequested = Signal(str)
    historyFilteredRequested = Signal(str)  # Filter: "all", "success", "failed"

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("Transparent")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(26, 22, 26, 26)
        layout.setSpacing(16)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        self.subtitle = QLabel("Local, offline document correction — nothing leaves this computer.")
        self.subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        new_button = QPushButton("New correction")
        new_button.setObjectName("Primary")
        new_button.setIcon(make_icon("add", "#FFFFFF", 16))
        new_button.clicked.connect(self.newCorrectionRequested.emit)
        header.addWidget(new_button)
        layout.addLayout(header)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(12)
        self.stat_total = StatCard("Total images processed", "studio")
        self.stat_success = StatCard("Successful corrections", "check", "#15803D")
        self.stat_failed = StatCard("Failed detections", "warning", "#B45309")
        self.stat_batches = StatCard("Batch jobs completed", "batch")
        for index, card in enumerate(
            (self.stat_total, self.stat_success, self.stat_failed, self.stat_batches)
        ):
            stats.addWidget(card, 0, index)
        layout.addLayout(stats)

        # Connect stat cards to history filter
        self.stat_total.clicked.connect(lambda: self.historyFilteredRequested.emit("all"))
        self.stat_success.clicked.connect(lambda: self.historyFilteredRequested.emit("success"))
        self.stat_failed.clicked.connect(lambda: self.historyFilteredRequested.emit("failed"))
        self.stat_batches.clicked.connect(lambda: self.batchRequested.emit())

        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyState")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(28, 26, 28, 26)
        empty_layout.setSpacing(8)
        empty_icon = QLabel()
        empty_icon.setPixmap(make_icon("studio", "#2563EB", 34).pixmap(34, 34))
        empty_title = QLabel("No documents processed yet")
        empty_title.setObjectName("EmptyTitle")
        empty_body = QLabel(
            "Open a photo of an ID card, licence, Istimara or passport. The document is "
            "detected automatically, straightened to its real physical size, and exported as "
            "PNG, JPEG, TIFF or PDF. Everything stays on this computer."
        )
        empty_body.setObjectName("EmptyBody")
        empty_body.setWordWrap(True)
        empty_actions = QHBoxLayout()
        empty_actions.setSpacing(8)
        start = QPushButton("Start with a photo")
        start.setObjectName("Primary")
        start.clicked.connect(self.newCorrectionRequested.emit)
        batch = QPushButton("Open batch processing")
        batch.clicked.connect(self.batchRequested.emit)
        profiles = QPushButton("Review document profiles")
        profiles.clicked.connect(self.profilesRequested.emit)
        empty_actions.addWidget(start)
        empty_actions.addWidget(batch)
        empty_actions.addWidget(profiles)
        empty_actions.addStretch(1)
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_body)
        empty_layout.addSpacing(4)
        empty_layout.addLayout(empty_actions)
        layout.addWidget(self.empty_card)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        projects_card, projects_layout = _card()
        projects_header = QHBoxLayout()
        projects_title = QLabel("Recent projects")
        projects_title.setObjectName("SectionTitle")
        projects_header.addWidget(projects_title)
        projects_header.addStretch(1)
        projects_layout.addLayout(projects_header)
        self.projects_table = QTableWidget(0, 4)
        self.projects_table.setHorizontalHeaderLabels(["Name", "Document", "Status", "Updated"])
        self.projects_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.projects_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_table.verticalHeader().setVisible(False)
        self.projects_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.projects_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.projects_table.setShowGrid(False)
        self.projects_table.itemDoubleClicked.connect(self._open_project_record)
        self.projects_table.setMinimumHeight(220)
        projects_layout.addWidget(self.projects_table, 1)
        self.projects_empty = QLabel("No saved projects yet. Corrected documents appear here.")
        self.projects_empty.setObjectName("Hint")
        projects_layout.addWidget(self.projects_empty)
        main_row.addWidget(projects_card, 3)

        side = QVBoxLayout()
        side.setSpacing(14)
        actions_card, actions_layout = _card()
        actions_title = QLabel("Quick actions")
        actions_title.setObjectName("SectionTitle")
        actions_layout.addWidget(actions_title)
        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)
        actions = (
            ("New correction", "studio", self.newCorrectionRequested.emit),
            ("Batch processing", "batch", self.batchRequested.emit),
            ("Open project", "open", self.openProjectRequested.emit),
            ("Document profiles", "profiles", self.profilesRequested.emit),
        )
        for index, (label, icon_name, callback) in enumerate(actions):
            button = QPushButton(label)
            button.setObjectName("QuickAction")
            button.setIcon(make_icon(icon_name, "#2563EB", 18))
            row, column = divmod(index, 2)
            actions_grid.addWidget(button, row, column)
            button.clicked.connect(callback)
        actions_layout.addLayout(actions_grid)
        side.addWidget(actions_card)

        documents_card, documents_layout = _card()
        documents_title = QLabel("Recent documents")
        documents_title.setObjectName("SectionTitle")
        documents_layout.addWidget(documents_title)
        self.documents_list = QListWidget()
        self.documents_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.documents_list.setIconSize(QSize(118, 74))
        self.documents_list.setGridSize(QSize(140, 110))
        self.documents_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.documents_list.setMovement(QListWidget.Movement.Static)
        self.documents_list.setWordWrap(True)
        self.documents_list.setSpacing(4)
        self.documents_list.itemDoubleClicked.connect(self._open_document_record)
        self.documents_list.setMinimumHeight(220)
        documents_layout.addWidget(self.documents_list, 1)
        side.addWidget(documents_card, 1)
        main_row.addLayout(side, 2)
        layout.addLayout(main_row, 1)
        layout.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        stats = self.ctx.repository.dashboard_stats()
        self.stat_total.set_value(str(stats.total_processed))
        self.stat_success.set_value(str(stats.successful))
        self.stat_failed.set_value(str(stats.failed))
        self.stat_batches.set_value(str(stats.batches_completed))

        self.empty_card.setVisible(stats.total_processed == 0)
        self.projects_empty.setVisible(not stats.recent_projects)

        self.projects_table.setRowCount(0)
        for record in stats.recent_projects:
            row = self.projects_table.rowCount()
            self.projects_table.insertRow(row)
            name_item = QTableWidgetItem(record.name)
            name_item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.projects_table.setItem(row, 0, name_item)
            self.projects_table.setItem(row, 1, QTableWidgetItem(record.profile_name or "—"))
            status_item = QTableWidgetItem(record.status.replace("_", " ").title())
            status_item.setForeground(
                QColor(
                    "#15803D"
                    if record.status == "success"
                    else "#B91C1C"
                    if record.status == "failed"
                    else "#B45309"
                )
            )
            self.projects_table.setItem(row, 2, status_item)
            self.projects_table.setItem(
                row, 3, QTableWidgetItem(record.updated_at[:16].replace("T", " "))
            )

        self.documents_list.clear()
        for record in stats.recent_documents:
            icon = QIcon()
            if record.thumbnail_path and Path(record.thumbnail_path).exists():
                pixmap = QPixmap(record.thumbnail_path)
                if not pixmap.isNull():
                    icon = QIcon(
                        pixmap.scaled(
                            118,
                            74,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            if icon.isNull():
                icon = make_icon("profiles", "#94A3B8", 32)
            item = QListWidgetItem(icon, record.name)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setToolTip(f"{record.profile_name}\n{record.updated_at[:16].replace('T', ' ')}")
            self.documents_list.addItem(item)

    # --------------------------------------------------------------- actions
    def _open_project_record(self, item: QTableWidgetItem) -> None:
        row_item = self.projects_table.item(item.row(), 0)
        if row_item is not None:
            record_id = row_item.data(Qt.ItemDataRole.UserRole)
            if record_id:
                self.recordRequested.emit(str(record_id))

    def _open_document_record(self, item: QListWidgetItem) -> None:
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if record_id:
            self.recordRequested.emit(str(record_id))
