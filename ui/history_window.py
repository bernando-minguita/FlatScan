"""Processing history: review, reopen, export again, relink and delete."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import IMAGE_FILE_FILTER
from app.context import AppContext
from core import image_loader, pipeline
from core.edit_history import EditState
from core.pipeline import ProcessingSettings
from ui.export_window import QuickExportDialog
from ui.icons import make_icon


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    return frame, layout


class HistoryPage(QWidget):
    openProjectRequested = Signal(str)
    historyChanged = Signal()
    notifyRequested = Signal(str, str)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self._records: list = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Processing History")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Saved projects, detected corners and settings. Only file paths and metadata are stored."
        )
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search projects…")
        self.search_edit.setToolTip("Search by name, profile, or source path. Use 'status:success' or 'status:failed' to filter")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(220)
        self.search_edit.textChanged.connect(self.refresh)
        refresh_button = QPushButton("Refresh")
        refresh_button.setIcon(make_icon("refresh", "#334155", 15))
        refresh_button.setToolTip("Reload history from database")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.search_edit)
        header.addWidget(refresh_button)
        root.addLayout(header)

        table_card, table_layout = _card()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Name", "Document", "Status", "Source", "Output"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_details)
        self.table.itemDoubleClicked.connect(lambda _item: self._open_studio())
        table_layout.addWidget(self.table, 1)
        self.empty_label = QLabel(
            "No history yet. Projects are saved when you press Save project or export a correction."
        )
        self.empty_label.setObjectName("Hint")
        table_layout.addWidget(self.empty_label)
        root.addWidget(table_card, 3)

        details_card, details_layout = _card()
        details_header = QHBoxLayout()
        details_title = QLabel("Selected project")
        details_title.setObjectName("SectionTitle")
        details_header.addWidget(details_title)
        details_header.addStretch(1)
        self.missing_chip = QLabel("")
        self.missing_chip.setObjectName("ChipWarning")
        self.missing_chip.setVisible(False)
        details_header.addWidget(self.missing_chip)
        details_layout.addLayout(details_header)
        self.details_label = QLabel("Select a record to inspect and reopen it.")
        self.details_label.setObjectName("Hint")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.details_label)

        # Path copy buttons
        path_actions = QHBoxLayout()
        self.copy_source_button = QPushButton("Copy source path")
        self.copy_source_button.setObjectName("Ghost")
        self.copy_source_button.setIcon(make_icon("copy", "#334155", 14))
        self.copy_source_button.setToolTip("Copy the source image file path to clipboard")
        self.copy_source_button.clicked.connect(self._copy_source_path)
        self.copy_output_button = QPushButton("Copy output path")
        self.copy_output_button.setObjectName("Ghost")
        self.copy_output_button.setIcon(make_icon("copy", "#334155", 14))
        self.copy_output_button.setToolTip("Copy the exported file path to clipboard")
        self.copy_output_button.clicked.connect(self._copy_output_path)
        path_actions.addWidget(self.copy_source_button)
        path_actions.addWidget(self.copy_output_button)
        path_actions.addStretch(1)
        details_layout.addLayout(path_actions)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open in Studio")
        self.open_button.setObjectName("Primary")
        self.open_button.setToolTip("Open this project in the Correction Studio for further editing")
        self.open_button.clicked.connect(self._open_studio)
        self.export_button = QPushButton("Export again")
        self.export_button.setToolTip("Re-export this document with current or modified settings")
        self.export_button.clicked.connect(self._export_again)
        self.relink_button = QPushButton("Relink source")
        self.relink_button.setToolTip("Link this record to a moved or renamed source image")
        self.relink_button.clicked.connect(self._relink)
        self.open_source_button = QPushButton("Open source folder")
        self.open_source_button.setObjectName("Ghost")
        self.open_source_button.setToolTip("Open the folder containing the source image in File Explorer")
        self.open_source_button.clicked.connect(self._open_source_folder)
        self.delete_button = QPushButton("Delete record")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setIcon(make_icon("trash", "#B91C1C", 15))
        self.delete_button.setToolTip("Delete this history record (exported files are not deleted)")
        self.delete_button.clicked.connect(self._delete)
        self.clear_old_button = QPushButton("Purge old records")
        self.clear_old_button.setObjectName("Ghost")
        self.clear_old_button.setToolTip("Delete history records older than the retention period set in Settings")
        self.clear_old_button.clicked.connect(self._purge_old)
        actions.addWidget(self.open_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.relink_button)
        actions.addWidget(self.open_source_button)
        actions.addStretch(1)
        actions.addWidget(self.clear_old_button)
        actions.addWidget(self.delete_button)
        details_layout.addLayout(actions)
        root.addWidget(details_card)
        self._set_actions_enabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.open_button,
            self.export_button,
            self.relink_button,
            self.open_source_button,
            self.delete_button,
            self.copy_source_button,
            self.copy_output_button,
        ):
            button.setEnabled(enabled)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        search = self.search_edit.text().strip()
        status_filter = None
        if search.startswith("status:"):
            status_filter = search[7:]  # Remove "status:" prefix
            search = ""
        self._records = self.ctx.repository.list_projects(limit=500, search=search, status=status_filter)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for record in self._records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            date_item = QTableWidgetItem(record.updated_at[:16].replace("T", " "))
            date_item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.table.setItem(row, 0, date_item)
            self.table.setItem(row, 1, QTableWidgetItem(record.name))
            self.table.setItem(row, 2, QTableWidgetItem(record.profile_name or "—"))
            status_item = QTableWidgetItem(record.status.replace("_", " ").title())
            status_item.setForeground(
                QColor(
                    "#15803D" if record.status == "success" else "#B91C1C" if record.status == "failed" else "#B45309"
                )
            )
            self.table.setItem(row, 3, status_item)
            source_missing = bool(record.source_path) and not Path(record.source_path).exists()
            source_item = QTableWidgetItem(
                (Path(record.source_path).name if record.source_path else "—")
                + ("  (missing)" if source_missing else "")
            )
            source_item.setToolTip(record.source_path)
            if source_missing:
                source_item.setForeground(QColor("#B91C1C"))
            self.table.setItem(row, 4, source_item)
            output_item = QTableWidgetItem(
                Path(record.output_path).name if record.output_path else "—"
            )
            output_item.setToolTip(record.output_path)
            self.table.setItem(row, 5, output_item)
        self.table.blockSignals(False)
        self.empty_label.setVisible(not self._records)
        if self._records:
            self.table.selectRow(0)
        else:
            self._set_actions_enabled(False)
            self.details_label.setText("Select a record to inspect and reopen it.")
            self.missing_chip.setVisible(False)

    def _selected_record(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def _update_details(self) -> None:
        record = self._selected_record()
        if record is None:
            self._set_actions_enabled(False)
            return
        self._set_actions_enabled(True)
        missing = bool(record.source_path) and not Path(record.source_path).exists()
        self.missing_chip.setVisible(missing)
        self.missing_chip.setText("Source image missing")
        settings = record.settings or {}
        parts = [
            f"<b>{record.name}</b> — {record.profile_name or 'no profile'}",
            f"Source: {record.source_path or '—'}",
            f"Output: {record.output_path or '—'}",
            f"Rotation: {settings.get('rotation', 0)}°  ·  DPI: {settings.get('dpi', '—')}  ·  "
            f"Corners saved: {'yes' if record.corners else 'no'}",
            f"Last updated: {record.updated_at[:16].replace('T', ' ')}",
        ]
        if record.error:
            parts.append(f"<span style='color:#B91C1C'>Error: {record.error}</span>")
        if missing:
            parts.append(
                "<span style='color:#B45309'>The original image was moved or deleted. "
                "Relink the source to reopen this project.</span>"
            )
        self.details_label.setText("<br>".join(parts))

    # --------------------------------------------------------------- actions
    def _open_studio(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if not record.source_path or not Path(record.source_path).exists():
            answer = QMessageBox.question(
                self,
                "Original image missing",
                "The original image could not be found. Relink it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._relink()
            return
        self.openProjectRequested.emit(record.id)

    def _relink(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the moved source image", str(Path(record.source_path).parent) if record.source_path else "", IMAGE_FILE_FILTER
        )
        if not path:
            return
        try:
            self.ctx.projects.relink_source(record, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not relink", str(exc))
            return
        self.refresh()
        self.notifyRequested.emit("Source image relinked.", "success")

    def _open_source_folder(self) -> None:
        record = self._selected_record()
        if record is None or not record.source_path:
            return
        folder = Path(record.source_path).parent
        if not folder.exists():
            QMessageBox.warning(self, "Folder missing", f"The folder no longer exists:\n{folder}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _copy_source_path(self) -> None:
        record = self._selected_record()
        if record is None or not record.source_path:
            return
        QApplication.clipboard().setText(record.source_path)
        self.notifyRequested.emit("Source path copied to clipboard.", "info")

    def _copy_output_path(self) -> None:
        record = self._selected_record()
        if record is None or not record.output_path:
            self.notifyRequested.emit("No output path to copy.", "warning")
            return
        QApplication.clipboard().setText(record.output_path)
        self.notifyRequested.emit("Output path copied to clipboard.", "info")

    def _export_again(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if not record.source_path or not Path(record.source_path).exists():
            QMessageBox.warning(
                self,
                "Original image missing",
                "This record cannot be re-exported because the source image is missing.",
            )
            return
        profile = self.ctx.repository.get_profile(record.profile_id) or self.ctx.current_profile()
        settings = record.settings or {}
        try:
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            loaded = image_loader.load_image(record.source_path)
            state = EditState.from_dict(
                settings | {"corners": record.corners},
                fallback_size=(loaded.width, loaded.height),
            )
            processing = ProcessingSettings(
                width_mm=float(settings.get("width_mm") or profile.width_mm),
                height_mm=float(settings.get("height_mm") or profile.height_mm),
                dpi=int(settings.get("dpi") or profile.dpi),
                rotation=state.rotation,
                auto_orientation=state.auto_orientation,
                interpolation=state.interpolation,
                enhancement=state.enhancement,
            )
            document = pipeline.correct_document(loaded.image, state.corners, processing)
        except Exception as exc:  # noqa: BLE001
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Could not rebuild the correction", str(exc))
            return
        QGuiApplication.restoreOverrideCursor()

        dialog = QuickExportDialog(
            self.ctx, document.image, Path(record.source_path).stem, profile, side=record.side, parent=self
        )
        if dialog.exec() != QuickExportDialog.DialogCode.Accepted:
            return
        paths = dialog.exported_paths()
        if paths:
            record.output_path = str(paths[0])
            self.ctx.projects.mark_exported(record)
            self.refresh()
            self.historyChanged.emit()
            self.notifyRequested.emit(f"Exported {paths[0].name}", "success")

    def _delete(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        if self.ctx.config.get("confirm_delete", True):
            answer = QMessageBox.question(
                self,
                "Delete history record",
                f"Delete the history record '{record.name}'?\n\n"
                "Exported files and the original image on disk are not deleted.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.ctx.projects.delete(record.id)
        self.refresh()
        self.historyChanged.emit()
        self.notifyRequested.emit("History record deleted.", "info")

    def _purge_old(self) -> None:
        days = int(self.ctx.config.get("history_retention_days", 0) or 0)
        if days <= 0:
            QMessageBox.information(
                self,
                "Retention is disabled",
                "History retention is set to 'keep forever'. Set a retention period in Settings first.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Purge old records",
            f"Delete history records older than {days} days? Exported files are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.ctx.projects.purge_old(days)
        self.refresh()
        self.historyChanged.emit()
        self.notifyRequested.emit(f"Removed {removed} old record(s).", "info")
