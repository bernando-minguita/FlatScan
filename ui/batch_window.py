"""Batch Processing: queue, settings, pairing, progress and failure handling."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    DPI_CHOICES,
    IMAGE_FILE_FILTER,
    OVERWRITE_POLICIES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REVIEW,
    STATUS_SUCCESS,
)
from app.context import AppContext
from database.models import BatchJobRecord
from services import batch_service
from services.batch_service import BatchConfig, PairGroup, pair_by_filename
from ui.icons import make_icon
from ui.widgets.image_preview import ImagePreview
from ui.widgets.progress_panel import ProgressPanel
from workers.batch_worker import BatchWorker
from workers.image_worker import LatestTaskWorker

STATUS_LABELS = {
    STATUS_PENDING: "Pending",
    STATUS_SUCCESS: "Completed",
    STATUS_FAILED: "Failed",
    STATUS_REVIEW: "Needs review",
    "processing": "Processing…",
    "paused": "Paused",
}
STATUS_COLORS = {
    STATUS_SUCCESS: "#15803D",
    STATUS_FAILED: "#B91C1C",
    STATUS_REVIEW: "#B45309",
    STATUS_PENDING: "#64748B",
    "processing": "#2563EB",
}


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(9)
    return frame, layout


def pairs_pdf_task(payload: dict) -> dict:
    pairs = payload["pairs"]
    return batch_service.export_pairs_to_pdf(pairs, payload["config"], payload["output_dir"])


class BatchPage(QWidget):
    historyChanged = Signal()
    reviewRequested = Signal(str)
    notifyRequested = Signal(str, str)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self._rows: list[dict] = []
        self._row_index: dict[str, int] = {}
        self._worker: BatchWorker | None = None
        self._job_id: str | None = None
        self._pair_worker: LatestTaskWorker | None = None
        self._last_config: BatchConfig | None = None
        self._last_output_dir: Path | None = None
        self._build_ui()
        self._refresh_profiles()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Batch Processing")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Process hundreds of photos with automatic detection. Failed images never stop the batch."
        )
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.add_files_button = QPushButton("Add files")
        self.add_files_button.setIcon(make_icon("add", "#334155", 16))
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button = QPushButton("Add folder")
        self.add_folder_button.setIcon(make_icon("folder", "#334155", 16))
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setObjectName("Ghost")
        self.remove_button.clicked.connect(self._remove_selected)
        header.addWidget(self.remove_button)
        header.addWidget(self.add_folder_button)
        header.addWidget(self.add_files_button)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QVBoxLayout()
        left.setSpacing(10)
        queue_card, queue_layout = _card()
        queue_header = QHBoxLayout()
        self.queue_summary = QLabel("No files in the queue")
        self.queue_summary.setObjectName("SectionTitle")
        queue_header.addWidget(self.queue_summary)
        queue_header.addStretch(1)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("Ghost")
        self.clear_button.clicked.connect(self._clear)
        queue_header.addWidget(self.clear_button)
        queue_layout.addLayout(queue_header)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["File", "Side", "Document ID", "Status", "Details", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Enable drag and drop reordering
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDragDropOverwriteMode(False)
        self.table.itemSelectionChanged.connect(self._update_preview)
        self.table.itemDoubleClicked.connect(lambda _item: self._review_selected())
        queue_layout.addWidget(self.table, 1)
        self.empty_hint = QLabel(
            "Add photos or a folder to begin. You can also assign front and back sides for pairing."
        )
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        queue_layout.addWidget(self.empty_hint)
        left.addWidget(queue_card, 3)

        preview_card, preview_layout = _card()
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("File preview"))
        preview_header.addStretch(1)
        self.preview_name = QLabel("")
        self.preview_name.setObjectName("Hint")
        preview_header.addWidget(self.preview_name)
        preview_layout.addLayout(preview_header)
        self.preview = ImagePreview()
        self.preview.set_empty_text("Select a file in the queue to see it here.")
        self.preview.setMinimumHeight(160)
        preview_layout.addWidget(self.preview, 1)
        left.addWidget(preview_card, 2)

        left_widget = QWidget()
        left_widget.setObjectName("Transparent")
        left_widget.setLayout(left)
        splitter.addWidget(left_widget)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setMinimumWidth(320)
        settings_scroll.setMaximumWidth(380)
        settings = QWidget()
        settings.setObjectName("Transparent")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 8, 0)
        settings_layout.setSpacing(10)

        profile_card, profile_layout = _card()
        profile_layout.addWidget(QLabel("Processing settings"))
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Select document profile for physical dimensions and default output format")
        profile_layout.addWidget(self.profile_combo)
        form = QFormLayout()
        form.setSpacing(8)
        self.sensitivity_slider = QSpinBox()
        self.sensitivity_slider.setRange(0, 100)
        self.sensitivity_slider.setSuffix(" %")
        self.sensitivity_slider.setToolTip("Detection sensitivity: lower = stricter, higher = more permissive")
        self.sensitivity_slider.setValue(int(float(ctx_value(self.ctx, "detection_sensitivity", 0.5)) * 100))
        self.auto_detect_check = QCheckBox("Detect document automatically")
        self.auto_detect_check.setToolTip("Automatically detect document corners for each image")
        self.auto_detect_check.setChecked(bool(self.ctx.config.get("batch_auto_detect", True)))
        self.auto_enhance_check = QCheckBox("Apply automatic enhancement")
        self.auto_enhance_check.setToolTip("Apply auto-enhancement (brightness, contrast, etc.) to each image")
        self.auto_enhance_check.setChecked(bool(self.ctx.config.get("auto_enhance", False)))
        self.continue_check = QCheckBox("Continue when a file fails")
        self.continue_check.setToolTip("Don't stop the batch if one file fails to process")
        self.continue_check.setChecked(bool(self.ctx.config.get("batch_continue_on_error", True)))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["JPEG", "PNG", "TIFF", "PDF"])
        self.format_combo.setToolTip("Output file format for processed images")
        default_format = str(self.ctx.config.get("default_format", "JPEG"))
        if default_format in ("JPEG", "PNG", "TIFF", "PDF"):
            self.format_combo.setCurrentText(default_format)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems([str(value) for value in DPI_CHOICES])
        self.dpi_combo.setEditable(True)
        self.dpi_combo.setToolTip("Output resolution in DPI (dots per inch)")
        self.dpi_combo.setCurrentText(str(self.ctx.config.get("default_dpi", 300)))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setValue(int(self.ctx.config.get("jpeg_quality", 95)))
        self.quality_spin.setSuffix(" %")
        self.quality_spin.setToolTip("JPEG quality (50-100). Only applies to JPEG format")
        self.output_edit = QLineEdit(str(self.ctx.config.get("output_dir")))
        self.output_edit.setToolTip("Folder where processed files will be saved")
        browse = QPushButton()
        browse.setIcon(make_icon("folder", "#475569", 16))
        browse.setToolTip("Choose output folder")
        browse.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.setSpacing(6)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse)
        self.template_edit = QLineEdit(str(self.ctx.config.get("filename_template", "{name}_{profile}")))
        self.template_edit.setToolTip("Filename template. Tokens: {name} {profile} {side} {date} {time} {dpi} {index}")
        self.policy_combo = QComboBox()
        for value, label in OVERWRITE_POLICIES:
            self.policy_combo.addItem(label, value)
        self.policy_combo.setToolTip("What to do when output file already exists")
        form.addRow("Sensitivity", self.sensitivity_slider)
        form.addRow("", self.auto_detect_check)
        form.addRow("Auto enhance", self.auto_enhance_check)
        form.addRow("On failure", self.continue_check)
        form.addRow("Format", self.format_combo)
        form.addRow("DPI", self.dpi_combo)
        form.addRow("Quality", self.quality_spin)
        form.addRow("Output folder", output_row)
        form.addRow("Filename", self.template_edit)
        form.addRow("If file exists", self.policy_combo)
        profile_layout.addLayout(form)
        settings_layout.addWidget(profile_card)

        pairing_card, pairing_layout = _card()
        pairing_layout.addWidget(QLabel("Front / back pairing"))
        pairing_hint = QLabel(
            "Select rows and mark them as front or back. Pairing groups the two sides under one "
            "document ID for a combined PDF, while each side is still exported on its own."
        )
        pairing_hint.setObjectName("Hint")
        pairing_hint.setWordWrap(True)
        pairing_layout.addWidget(pairing_hint)
        pairing_grid = QGridLayout()
        pairing_grid.setSpacing(6)
        self.front_button = QPushButton("Mark front")
        self.front_button.setToolTip("Mark selected files as front side of document")
        self.front_button.clicked.connect(lambda: self._assign_side("front"))
        self.back_button = QPushButton("Mark back")
        self.back_button.setToolTip("Mark selected files as back side of document")
        self.back_button.clicked.connect(lambda: self._assign_side("back"))
        self.unpair_button = QPushButton("Clear pairing")
        self.unpair_button.setObjectName("Ghost")
        self.unpair_button.setToolTip("Remove front/back assignment and document ID from selected files")
        self.unpair_button.clicked.connect(self._clear_pairing)
        self.auto_pair_button = QPushButton("Auto-pair by filename")
        self.auto_pair_button.setToolTip("Automatically pair front/back based on filename patterns (e.g., _front, _back)")
        self.auto_pair_button.clicked.connect(self._auto_pair)
        self.pair_pdf_button = QPushButton("Export paired PDFs")
        self.pair_pdf_button.setIcon(make_icon("pdf", "#334155", 15))
        self.pair_pdf_button.setToolTip("Export front/back pairs as combined PDF documents")
        self.pair_pdf_button.clicked.connect(self._export_pairs)
        pairing_grid.addWidget(self.front_button, 0, 0)
        pairing_grid.addWidget(self.back_button, 0, 1)
        pairing_grid.addWidget(self.unpair_button, 1, 0)
        pairing_grid.addWidget(self.auto_pair_button, 1, 1)
        pairing_grid.addWidget(self.pair_pdf_button, 2, 0, 1, 2)
        pairing_layout.addLayout(pairing_grid)
        settings_layout.addWidget(pairing_card)
        settings_layout.addStretch(1)
        settings_scroll.setWidget(settings)
        splitter.addWidget(settings_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 340])
        root.addWidget(splitter, 1)

        bottom_card, bottom_layout = _card()
        counters = QGridLayout()
        counters.setHorizontalSpacing(18)
        self.counter_labels: dict[str, QLabel] = {}
        for index, key in enumerate(("Total", "Pending", "Completed", "Failed", "Needs review")):
            caption = QLabel(key)
            caption.setObjectName("Tiny")
            value = QLabel("0")
            value.setObjectName("SectionTitle")
            counters.addWidget(caption, 0, index * 2)
            counters.addWidget(value, 1, index * 2)
            self.counter_labels[key] = value
        self.current_label = QLabel("Ready")
        self.current_label.setObjectName("Hint")
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        counters.addWidget(self.current_label, 0, 10, 2, 1)
        bottom_layout.addLayout(counters)
        self.progress = ProgressPanel("Cancel batch")
        self.progress.cancelRequested.connect(self._cancel)
        bottom_layout.addWidget(self.progress)
        self._open_folder_button = QPushButton("Open folder")
        self._open_folder_button.setIcon(make_icon("folder", "#475569", 14))
        self._open_folder_button.setToolTip("Open the batch output folder")
        self._open_folder_button.setVisible(False)
        self._open_folder_button.clicked.connect(self._open_last_output_folder)
        bottom_layout.addWidget(self._open_folder_button)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Start batch")
        self.start_button.setObjectName("Primary")
        self.start_button.setIcon(make_icon("batch", "#FFFFFF", 16))
        self.start_button.clicked.connect(lambda: self._start())
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.retry_button = QPushButton("Retry failed")
        self.retry_button.clicked.connect(self._retry_failed)
        self.review_button = QPushButton("Open selected in Studio")
        self.review_button.clicked.connect(self._review_selected)
        actions.addWidget(self.start_button)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.retry_button)
        actions.addStretch(1)
        actions.addWidget(self.review_button)
        bottom_layout.addLayout(actions)
        root.addWidget(bottom_card)
        self._update_counts()

    def _refresh_profiles(self) -> None:
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        profiles = self.ctx.profiles(active_only=True) or self.ctx.profiles()
        for profile in profiles:
            self.profile_combo.addItem(profile.name)
        if current:
            index = self.profile_combo.findText(current)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ queue
    def add_files(self, paths: list[str]) -> None:
        added = 0
        for entry in paths:
            path = Path(entry)
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in self._row_index:
                continue
            self._rows.append(
                {"path": path, "side": "", "doc_id": "", "status": STATUS_PENDING, "output": "", "error": ""}
            )
            self._row_index[key] = len(self._rows) - 1
            added += 1
        if added:
            self._rebuild_table()
            self.notifyRequested.emit(f"Added {added} file{'s' if added != 1 else ''}.", "info")

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add images to the batch", "", IMAGE_FILE_FILTER)
        self.add_files(files)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder of images")
        if not folder:
            return
        try:
            paths = batch_service.collect_images([folder])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Folder could not be read", str(exc))
            return
        if not paths:
            QMessageBox.information(self, "No images", "No supported images were found in that folder.")
            return
        self.add_files([str(path) for path in paths])

    def _remove_selected(self) -> None:
        if self._is_running():
            QMessageBox.information(self, "Batch running", "Pause or cancel the batch before editing the queue.")
            return
        rows = sorted((index.row() for index in self.table.selectionModel().selectedRows()), reverse=True)
        for row in rows:
            if 0 <= row < len(self._rows):
                self._rows.pop(row)
        self._rebuild_table()

    def _clear(self) -> None:
        if self._is_running():
            QMessageBox.information(self, "Batch running", "Pause or cancel the batch before clearing the queue.")
            return
        self._rows.clear()
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._row_index = {}
        for index, entry in enumerate(self._rows):
            self._row_index[str(entry["path"].resolve()).lower()] = index
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry["path"].name))
            self.table.setItem(row, 1, QTableWidgetItem(entry["side"].title() if entry["side"] else "—"))
            self.table.setItem(row, 2, QTableWidgetItem(entry["doc_id"] or "—"))
            self._set_status_cell(row, entry["status"])
            detail = entry["output"] or entry["error"]
            self.table.setItem(row, 4, QTableWidgetItem(detail))
            if entry["error"]:
                self.table.item(row, 4).setToolTip(entry["error"])
            # Duration column (column 5)
            duration_str = entry.get("duration", "")
            if duration_str:
                self.table.setItem(row, 5, QTableWidgetItem(duration_str))
        self.table.blockSignals(False)
        self.empty_hint.setVisible(not self._rows)
        self._update_counts()
        self._update_preview()
        self.queue_summary.setText(
            f"{len(self._rows)} file{'s' if len(self._rows) != 1 else ''} in the queue"
            if self._rows
            else "No files in the queue"
        )

    def dropEvent(self, event) -> None:
        """Handle row reordering via drag and drop."""
        if self._is_running():
            event.ignore()
            return
        # Get the target row where the drop occurred
        target_row = self.table.dropIndicatorPosition()
        if target_row == QAbstractItemView.DropIndicatorPosition.OnItem:
            target_row = self.table.indexAt(event.position().toPoint()).row()
        elif target_row == QAbstractItemView.DropIndicatorPosition.AboveItem:
            target_row = self.table.indexAt(event.position().toPoint()).row()
        elif target_row == QAbstractItemView.DropIndicatorPosition.BelowItem:
            target_row = self.table.indexAt(event.position().toPoint()).row() + 1
        else:
            target_row = self.table.rowCount()

        # Get selected rows (source rows)
        selected_rows = sorted(self._selected_rows())
        if not selected_rows:
            event.ignore()
            return

        # Move rows in _rows list
        # We need to move them as a block to preserve relative order
        moved_entries = [self._rows[row] for row in selected_rows]
        # Remove from original positions (from highest to lowest to not affect indices)
        for row in reversed(selected_rows):
            self._rows.pop(row)
        # Insert at target position
        # Adjust target_row if we removed rows before it
        adjusted_target = target_row
        for row in selected_rows:
            if row < target_row:
                adjusted_target -= 1
        adjusted_target = max(0, min(adjusted_target, len(self._rows)))
        for i, entry in enumerate(moved_entries):
            self._rows.insert(adjusted_target + i, entry)

        self._rebuild_table()
        # Re-select the moved rows
        self.table.blockSignals(True)
        for i in range(len(moved_entries)):
            self.table.selectRow(adjusted_target + i)
        self.table.blockSignals(False)
        event.acceptProposedAction()

    def _set_status_cell(self, row: int, status: str) -> None:
        item = QTableWidgetItem(STATUS_LABELS.get(status, status.title()))
        item.setForeground(QColor(STATUS_COLORS.get(status, "#334155")))
        self.table.setItem(row, 3, item)

    def _update_counts(self) -> None:
        total = len(self._rows)
        pending = sum(1 for row in self._rows if row["status"] == STATUS_PENDING)
        completed = sum(1 for row in self._rows if row["status"] == STATUS_SUCCESS)
        failed = sum(1 for row in self._rows if row["status"] == STATUS_FAILED)
        review = sum(1 for row in self._rows if row["status"] == STATUS_REVIEW)
        values = {
            "Total": total,
            "Pending": pending,
            "Completed": completed,
            "Failed": failed,
            "Needs review": review,
        }
        for key, value in values.items():
            self.counter_labels[key].setText(str(value))

    def _update_preview(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self.preview.clear()
            self.preview_name.setText("")
            return
        index = rows[0].row()
        if index < 0 or index >= len(self._rows):
            return
        entry = self._rows[index]
        self.preview_name.setText(entry["path"].name)
        try:
            from core.image_loader import load_image

            self.preview.set_image(load_image(entry["path"]).image)
        except Exception as exc:  # noqa: BLE001
            self.preview.clear()
            self.preview_name.setText(str(exc))

    # ----------------------------------------------------------------- config
    def _config(self) -> BatchConfig:
        profile = self.ctx.profile_by_name(self.profile_combo.currentText()) or self.ctx.current_profile()
        try:
            dpi = int(float(self.dpi_combo.currentText()))
        except ValueError:
            dpi = profile.dpi
        fmt = self.format_combo.currentText()
        return BatchConfig(
            profile=profile,
            output_dir=Path(self.output_edit.text().strip() or str(self.ctx.config.get("output_dir"))),
            sensitivity=self.sensitivity_slider.value() / 100.0,
            auto_detect=self.auto_detect_check.isChecked(),
            fmt=fmt,
            dpi=max(72, min(1200, dpi)),
            quality=self.quality_spin.value(),
            template=self.template_edit.text().strip() or "{name}_{profile}",
            policy=self.policy_combo.currentData() or "rename",
            auto_enhance=self.auto_enhance_check.isChecked(),
            continue_on_error=self.continue_check.isChecked(),
            interpolation=str(self.ctx.config.get("interpolation", "Cubic")),
        )

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose batch output folder", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    # -------------------------------------------------------------- processing
    def _start(self, only: list[str] | None = None) -> None:
        if self._is_running():
            return
        if not self._rows:
            QMessageBox.information(self, "Queue is empty", "Add images before starting the batch.")
            return
        try:
            config = self._config()
            config.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Output folder", f"The output folder cannot be created:\n{exc}")
            return
        self._last_output_dir = config.output_dir
        if config.policy == "replace":
            answer = QMessageBox.question(
                self,
                "Replace existing files?",
                "Files with identical names in the output folder will be replaced. "
                "Source images are never replaced. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if only is None:
            targets = [entry for entry in self._rows if entry["status"] in (STATUS_PENDING, STATUS_FAILED, STATUS_REVIEW)]
        else:
            target_set = {str(Path(path).resolve()).lower() for path in only}
            targets = [entry for entry in self._rows if str(entry["path"].resolve()).lower() in target_set]
        if not targets:
            QMessageBox.information(self, "Nothing to process", "There are no pending files in the queue.")
            return
        for entry in targets:
            entry["status"] = STATUS_PENDING
            entry["error"] = ""
            entry["output"] = ""
        self._rebuild_table()

        self._last_config = config
        self._job_id = str(uuid.uuid4())
        try:
            self.ctx.repository.create_batch_job(
                BatchJobRecord(
                    id=self._job_id,
                    name=f"Batch {len(targets)} files",
                    profile_name=config.profile.name,
                    output_dir=str(config.output_dir),
                    total=len(targets),
                    status="running",
                )
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "History unavailable", f"The batch will run, but could not be recorded:\n{exc}")

        self._worker = BatchWorker([entry["path"] for entry in targets], config, self)
        self._worker.itemStarted.connect(self._on_item_started)
        self._worker.itemFinished.connect(self._on_item_finished)
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.stateChanged.connect(self._on_state)
        self._worker.batchFinished.connect(self._on_finished)
        self._set_busy(True)
        self.progress.set_progress(0, len(targets), "Batch running…", cancellable=False)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.pause_button.setEnabled(busy)
        self.pause_button.setText("Pause")
        for widget in (
            self.profile_combo,
            self.sensitivity_slider,
            self.auto_detect_check,
            self.auto_enhance_check,
            self.continue_check,
            self.format_combo,
            self.dpi_combo,
            self.quality_spin,
            self.output_edit,
            self.template_edit,
            self.policy_combo,
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.front_button,
            self.back_button,
            self.unpair_button,
            self.auto_pair_button,
            self.pair_pdf_button,
            self.retry_button,
        ):
            widget.setEnabled(not busy)
        self.progress.cancel_button.setVisible(busy)

    def _row_for_path(self, path: str) -> int | None:
        try:
            return self._row_index.get(str(Path(path).resolve()).lower())
        except OSError:
            return None

    def _on_item_started(self, index: int, path: str) -> None:
        self.current_label.setText(f"Processing {Path(path).name}")
        row = self._row_for_path(path)
        if row is not None and 0 <= row < len(self._rows):
            self._rows[row]["status"] = "processing"
            self._set_status_cell(row, "processing")
            self.table.scrollToItem(self.table.item(row, 0))

    def _on_item_finished(self, index: int, result) -> None:
        row = self._row_for_path(result.source_path)
        if row is None:
            return
        index = row
        entry = self._rows[index]
        entry["status"] = result.status
        entry["output"] = result.output_path
        entry["error"] = result.error
        entry["duration"] = result.duration_str if hasattr(result, 'duration_str') else ""
        self.table.setItem(index, 4, QTableWidgetItem(result.output_path or result.error))
        if entry["duration"]:
            self.table.setItem(index, 5, QTableWidgetItem(entry["duration"]))
        self._set_status_cell(index, result.status)
        self._update_counts()
        if self._job_id:
            try:
                self.ctx.repository.add_batch_item(
                    self._job_id,
                    result.source_path,
                    status=result.status,
                    output_path=result.output_path,
                    confidence=result.confidence,
                    error=result.error,
                )
            except Exception:  # noqa: BLE001 - history must not break the batch
                pass

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.set_progress(done, total, f"Processing {done} of {total}", self.current_label.text())

    def _on_state(self, state: str) -> None:
        if state == "paused":
            self.pause_button.setText("Resume")
            self.progress.set_busy("Batch paused", "Press Resume to continue", cancellable=True)
        elif state == "running":
            self.pause_button.setText("Pause")
            self.progress.cancel_button.setVisible(True)
        elif state == "cancelling":
            self.progress.set_busy("Cancelling…", cancellable=False)

    def _on_finished(self, summary: dict) -> None:
        succeeded = summary.get("succeeded", 0)
        failed = summary.get("failed", 0)
        cancelled = summary.get("cancelled", False)
        text = (
            "Batch cancelled"
            if cancelled
            else f"Batch complete — {succeeded} succeeded, {failed} need attention"
        )
        self.progress.set_complete(
            text,
            "Needs-review files can be opened in the Correction Studio and fixed manually.",
            problem=failed > 0,
        )
        self.current_label.setText("Ready")
        if self._job_id:
            try:
                self.ctx.repository.update_batch_job(
                    self._job_id,
                    succeeded=succeeded,
                    failed=failed,
                    status="cancelled" if cancelled else "completed",
                    finish=True,
                )
            except Exception:  # noqa: BLE001
                pass
        self._worker = None
        self._job_id = None
        self._set_busy(False)
        self._update_counts()
        if succeeded > 0:
            self._open_folder_button.setVisible(True)
        else:
            self._open_folder_button.setVisible(False)
        self.historyChanged.emit()
        self.notifyRequested.emit(text, "warning" if failed else "success")

    def _toggle_pause(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            return
        if self._worker.is_paused:
            self._worker.resume()
        else:
            self._worker.pause()

    def _cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.progress.set_busy("Cancelling after the current file…", cancellable=False)

    def _retry_failed(self) -> None:
        if self._is_running():
            return
        failed = [
            str(entry["path"])
            for entry in self._rows
            if entry["status"] in (STATUS_FAILED, STATUS_REVIEW)
        ]
        if not failed:
            QMessageBox.information(self, "Nothing to retry", "There are no failed files in the queue.")
            return
        self._start(only=failed)

    # ---------------------------------------------------------------- pairing
    def _selected_rows(self) -> list[int]:
        return [index.row() for index in self.table.selectionModel().selectedRows()]

    def _assign_side(self, side: str) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Select files", "Select one or more rows first.")
            return
        used_ids = {entry["doc_id"] for entry in self._rows if entry["doc_id"]}
        for row in rows:
            entry = self._rows[row]
            if not entry["doc_id"]:
                base = entry["path"].stem
                candidate = batch_service.pair_key(entry["path"])
                suffix = 2
                while candidate in used_ids and candidate != base:
                    candidate = f"{base}_{suffix}"
                    suffix += 1
                entry["doc_id"] = candidate
                used_ids.add(candidate)
            entry["side"] = side
        self._rebuild_table()

    def _clear_pairing(self) -> None:
        for row in self._selected_rows() or range(len(self._rows)):
            self._rows[row]["side"] = ""
            self._rows[row]["doc_id"] = ""
        self._rebuild_table()

    def _auto_pair(self) -> None:
        if not self._rows:
            return
        groups = pair_by_filename([entry["path"] for entry in self._rows])
        paired = 0
        conflicts: list[str] = []
        for group in groups:
            conflicts.extend(group.conflicts)
            for path in group.paths():
                key = str(Path(path).resolve()).lower()
                index = self._row_index.get(key)
                if index is None:
                    continue
                side = "front" if group.front and Path(group.front).resolve() == Path(path).resolve() else "back"
                self._rows[index]["side"] = side
                self._rows[index]["doc_id"] = group.document_id
            if group.complete:
                paired += 1
        self._rebuild_table()
        if conflicts:
            self.notifyRequested.emit(
                "Some documents had more than one side with the same name; "
                f"the first file was kept. {'; '.join(conflicts[:2])}",
                "warning",
            )
        if paired:
            self.notifyRequested.emit(f"Paired {paired} front/back document(s).", "success")
        elif not conflicts:
            self.notifyRequested.emit(
                "No front/back pairs were found in the filenames. Assign the sides manually.", "warning"
            )

    def _export_pairs(self) -> None:
        if self._is_running():
            return
        if self._pair_worker is not None and self._pair_worker.isRunning():
            self.notifyRequested.emit("A paired PDF export is already running.", "warning")
            return
        groups: dict[str, PairGroup] = {}
        duplicates: list[str] = []
        for entry in self._rows:
            if not entry["doc_id"] or entry["side"] not in ("front", "back"):
                continue
            group = groups.setdefault(entry["doc_id"], PairGroup(document_id=entry["doc_id"]))
            if entry["side"] == "front":
                if group.front is None:
                    group.front = entry["path"]
                else:
                    duplicates.append(
                        f"{entry['doc_id']}: second front file {Path(entry['path']).name} is ignored."
                    )
            elif group.back is None:
                group.back = entry["path"]
            else:
                duplicates.append(
                    f"{entry['doc_id']}: second back file {Path(entry['path']).name} is ignored."
                )
        complete = [group for group in groups.values() if group.complete]
        if not complete:
            QMessageBox.information(
                self,
                "No complete pairs",
                "Assign a front and a back image to the same document ID first.",
            )
            return
        if duplicates:
            answer = QMessageBox.question(
                self,
                "Duplicate sides",
                "Some documents have more than one image assigned to the same side:\n"
                + "\n".join(duplicates[:5])
                + ("\n…" if len(duplicates) > 5 else "")
                + "\n\nThe first file of each side will be used. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        config = self._config()
        output_dir = config.output_dir
        if config.policy == "replace":
            answer = QMessageBox.question(
                self,
                "Replace existing PDFs?",
                "Existing paired PDFs with the same name will be replaced. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QMessageBox.information(
            self,
            "Export paired PDFs",
            f"{len(complete)} paired document(s) will be processed and saved as PDFs in:\n{output_dir}",
        )
        self._pair_worker = LatestTaskWorker(pairs_pdf_task, self)
        self._pair_worker.resultReady.connect(self._on_pairs_ready)
        self._pair_worker.taskFailed.connect(lambda _token, message: self.progress.set_idle("Pair export failed", message))
        self._pair_worker.start()
        self.progress.set_busy(f"Building {len(complete)} paired PDF(s)…", cancellable=False)
        self._pair_worker.submit(1, {"pairs": complete, "config": config, "output_dir": str(output_dir)})

    def _on_pairs_ready(self, _token: int, result: dict) -> None:
        paths = result.get("paths", []) or []
        errors = result.get("errors", []) or []
        summary = f"Created {len(paths)} paired PDF(s)"
        if errors:
            summary += f", {len(errors)} problem(s)"
        self.progress.set_idle(summary, errors[0] if errors else "")
        if paths:
            self.notifyRequested.emit(summary + ".", "warning" if errors else "success")
        else:
            self.notifyRequested.emit(
                errors[0] if errors else "No paired PDFs could be created.", "warning"
            )
        if self._pair_worker is not None:
            self._pair_worker.stop()
            self._pair_worker.wait()
            # The thread has finished; release its C++ resources now instead
            # of keeping one dead worker per paired export alive on the page.
            self._pair_worker.deleteLater()
            self._pair_worker = None

    def _review_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Select a file", "Select a row to open in the Studio.")
            return
        self.reviewRequested.emit(str(self._rows[rows[0]]["path"]))

    def _open_last_output_folder(self) -> None:
        """Open the batch output folder in the system file manager."""
        folder = self._last_output_dir
        if folder is None:
            folder = Path(self.output_edit.text().strip() or ".")
        if not folder.exists():
            QMessageBox.warning(
                self,
                "Folder not found",
                f"The batch output folder could not be found:\\n{folder}",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            # Wait for the current file to finish rather than destroying a
            # running QThread when the window closes.
            self._worker.wait()
        if self._pair_worker is not None:
            self._pair_worker.stop()
            self._pair_worker.wait()


def ctx_value(ctx: AppContext, key: str, default):
    return ctx.config.get(key, default)
