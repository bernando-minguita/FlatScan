"""Export dialogs and the Export Center page."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    DPI_CHOICES,
    IMAGE_FILE_FILTER,
    OVERWRITE_POLICIES,
    OVERWRITE_REPLACE,
)
from app.context import AppContext
from core import pdf_handler
from core.image_exporter import ExportError
from core.image_loader import ImageLoadError
from core.pdf_handler import PAGE_MODES
from database.models import DocumentProfile
from services.export_service import ExportItem, ExportOptions
from ui.icons import make_icon
from ui.widgets.image_preview import ImagePreview
from ui.widgets.progress_panel import ProgressPanel
from workers.export_worker import ExportWorker


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    return frame, layout


class HistoryPickerDialog(QDialog):
    """Pick previously processed documents to add to the export queue."""

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add from history")
        self.resize(720, 460)
        self._ctx = ctx
        self._records = ctx.repository.list_projects(limit=300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Profile", "Status", "Updated"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for record in self._records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(record.name))
            self.table.setItem(row, 1, QTableWidgetItem(record.profile_name))
            self.table.setItem(row, 2, QTableWidgetItem(record.status))
            self.table.setItem(row, 3, QTableWidgetItem(record.updated_at[:16].replace("T", " ")))
        layout.addWidget(self.table, 1)

        if not self._records:
            layout.addWidget(QLabel("No processed documents yet. Correct an image first."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_records(self) -> list:
        return [self._records[index.row()] for index in self.table.selectionModel().selectedRows()]


class PdfPreviewDialog(QDialog):
    def __init__(self, pages: list[np.ndarray], title: str = "PDF preview", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 620)
        self._pages = pages
        self._index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        self.preview = ImagePreview()
        self.preview.set_empty_text("No pages to preview.")
        layout.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        self.prev_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.page_label = QLabel("")
        self.page_label.setObjectName("Hint")
        self.prev_button.clicked.connect(lambda: self._show(self._index - 1))
        self.next_button.clicked.connect(lambda: self._show(self._index + 1))
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.page_label, 1)
        controls.addWidget(close)
        layout.addLayout(controls)
        self._show(0)

    def _show(self, index: int) -> None:
        if not self._pages:
            return
        self._index = max(0, min(len(self._pages) - 1, index))
        self.preview.set_image(self._pages[self._index])
        self.page_label.setText(f"Page {self._index + 1} of {len(self._pages)}")
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(self._index < len(self._pages) - 1)


class QuickExportDialog(QDialog):
    """Export the image currently open in the studio or history."""

    def __init__(
        self,
        ctx: AppContext,
        image: np.ndarray,
        source_name: str,
        profile: DocumentProfile | None,
        side: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export document")
        self.resize(780, 560)
        self._ctx = ctx
        self._image = image
        self._profile = profile
        self._source_name = source_name
        self._side = side
        self._exported: list[Path] = []

        defaults = ctx.exports.default_options()
        if profile is not None:
            defaults.dpi = int(profile.dpi)
            defaults.fmt = profile.format if profile.format in ("PNG", "JPEG", "TIFF", "PDF") else "JPEG"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        preview_card, preview_layout = _card()
        preview_layout.addWidget(QLabel("Preview"))
        self.preview = ImagePreview()
        self.preview.set_image(image)
        preview_layout.addWidget(self.preview, 1)
        dimensions = QLabel(f"{image.shape[1]} × {image.shape[0]} px at source")
        dimensions.setObjectName("Hint")
        preview_layout.addWidget(dimensions)
        layout.addWidget(preview_card, 1)

        form_card, form_layout = _card()
        form_layout.addWidget(QLabel("Export settings"))

        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPEG", "TIFF", "PDF"])
        self.format_combo.setCurrentText(defaults.fmt)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems([str(value) for value in DPI_CHOICES])
        self.dpi_combo.setEditable(True)
        self.dpi_combo.setCurrentText(str(defaults.dpi))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setValue(defaults.quality)
        self.quality_spin.setSuffix(" %")
        self.policy_combo = QComboBox()
        for value, label in OVERWRITE_POLICIES:
            self.policy_combo.addItem(label, value)
        self.policy_combo.setCurrentIndex(
            max(0, [value for value, _ in OVERWRITE_POLICIES].index(defaults.policy))
            if defaults.policy in [value for value, _ in OVERWRITE_POLICIES]
            else 0
        )

        self.template_edit = QLineEdit(defaults.template)
        self.template_edit.setToolTip("Tokens: {name} {profile} {side} {date} {time} {dpi}")

        self.dir_edit = QLineEdit(str(defaults.output_dir))
        browse = QPushButton()
        browse.setIcon(make_icon("folder", "#475569", 16))
        browse.setToolTip("Choose output folder")
        browse.clicked.connect(self._browse_dir)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)

        self.page_mode_combo = QComboBox()
        for value, label in PAGE_MODES.items():
            self.page_mode_combo.addItem(label, value)
        self.page_mode_combo.setCurrentIndex(4)

        form = QFormLayout()
        form.setSpacing(9)
        form.addRow("Format", self.format_combo)
        form.addRow("DPI", self.dpi_combo)
        form.addRow("JPEG quality", self.quality_spin)
        form.addRow("Output folder", dir_row)
        form.addRow("Filename template", self.template_edit)
        form.addRow("If file exists", self.policy_combo)
        form.addRow("PDF page size", self.page_mode_combo)
        form_layout.addLayout(form)

        hint = QLabel(
            "DPI metadata is embedded in PNG, JPEG and TIFF files. "
            "Original source images are never overwritten."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        form_layout.addWidget(hint)
        form_layout.addStretch(1)

        self.format_combo.currentTextChanged.connect(self._update_pdf_state)
        self._update_pdf_state(self.format_combo.currentText())

        buttons = QDialogButtonBox()
        self.preview_button = buttons.addButton("Preview PDF", QDialogButtonBox.ButtonRole.ActionRole)
        self.preview_button.clicked.connect(self._preview_pdf)
        export_button = buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        export_button.setObjectName("Primary")
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._do_export)
        buttons.rejected.connect(self.reject)
        form_layout.addWidget(buttons)

        layout.addWidget(form_card, 1)

    # ---------------------------------------------------------------- helpers
    def _browse_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.dir_edit.text())
        if folder:
            self.dir_edit.setText(folder)

    def _update_pdf_state(self, fmt: str) -> None:
        is_pdf = fmt == "PDF"
        self.page_mode_combo.setEnabled(is_pdf)
        self.quality_spin.setEnabled(not is_pdf)

    def _options(self) -> ExportOptions:
        try:
            dpi = int(float(self.dpi_combo.currentText()))
        except ValueError:
            dpi = 300
        return ExportOptions(
            fmt=self.format_combo.currentText(),
            dpi=max(72, min(1200, dpi)),
            quality=self.quality_spin.value(),
            output_dir=Path(self.dir_edit.text().strip() or "."),
            template=self.template_edit.text().strip() or "{name}_{profile}",
            policy=self.policy_combo.currentData(),
            include_profile=True,
            include_side=True,
            page_mode=self.page_mode_combo.currentData(),
        )

    def _preview_pdf(self) -> None:
        options = self._options()
        physical = None
        if self._profile is not None:
            physical = (self._profile.width_mm, self._profile.height_mm)
        try:
            data = pdf_handler.pdf_bytes_for_preview(
                [self._image],
                page_mode=options.page_mode,
                dpi=options.dpi,
                quality=min(90, options.quality),
                physical_mm=physical,
            )
            pages = pdf_handler.render_pdf_bytes(data, dpi=110)
        except (ExportError, ValueError) as exc:
            QMessageBox.critical(self, "PDF preview failed", str(exc))
            return
        PdfPreviewDialog(pages, "PDF preview", self).exec()

    def _do_export(self) -> None:
        options = self._options()
        profile_name = self._profile.name if self._profile else ""
        item = ExportItem(
            display_name=self._source_name,
            profile_name=profile_name,
            side=self._side,
            image=self._image,
            width_mm=self._profile.width_mm if self._profile else None,
            height_mm=self._profile.height_mm if self._profile else None,
        )
        if options.policy == OVERWRITE_REPLACE:
            confirm = QMessageBox.question(
                self,
                "Replace existing file?",
                "An existing file with the same name will be replaced. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        try:
            if options.normalized_format() == "PDF":
                target = self._ctx.exports.export_items_to_pdf([item], options, self._source_name)
                if target is None:
                    QMessageBox.information(self, "Export skipped", "The PDF was not written.")
                    return
                self._exported = [target]
            else:
                result = self._ctx.exports.export_item(item, options)
                if result is None or result.skipped:
                    QMessageBox.information(
                        self,
                        "Export skipped",
                        "The file already exists and the policy is set to skip.",
                    )
                    return
                self._exported = [result.path]
        except (ExportError, OSError, ImageLoadError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        self._ctx.config.set("output_dir", str(options.output_dir))
        self._ctx.config.set("default_format", options.fmt)
        self._ctx.config.set("jpeg_quality", options.quality)
        self._ctx.config.set("filename_template", options.template)
        self._ctx.config.set("overwrite_policy", options.policy)
        self._ctx.save_settings()
        self.accept()

    def exported_paths(self) -> list[Path]:
        return list(self._exported)


class ExportCenterPage(QWidget):
    historyChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self._ctx = ctx
        self._items: list[ExportItem] = []
        self._worker: ExportWorker | None = None
        self._cancelling = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Export Center")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Convert corrected documents to PNG, JPEG, TIFF or PDF with the right size and DPI."
        )
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        add_files = QPushButton("Add files")
        add_files.setIcon(make_icon("add", "#334155", 16))
        add_files.clicked.connect(self._add_files)
        add_history = QPushButton("Add from history")
        add_history.setIcon(make_icon("history", "#334155", 16))
        add_history.clicked.connect(self._add_from_history)
        clear = QPushButton("Clear list")
        clear.setObjectName("Ghost")
        clear.clicked.connect(self._clear_items)
        header.addWidget(add_files)
        header.addWidget(add_history)
        header.addWidget(clear)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        queue_card, queue_layout = _card()
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Export queue"))
        queue_header.addStretch(1)
        remove = QPushButton("Remove selected")
        remove.setObjectName("Ghost")
        remove.clicked.connect(self._remove_selected)
        queue_header.addWidget(remove)
        queue_layout.addLayout(queue_header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Profile", "Side", "Origin"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_preview)
        queue_layout.addWidget(self.table, 1)
        self.empty_label = QLabel(
            "The queue is empty. Add corrected images from disk or pick processed documents "
            "from the history."
        )
        self.empty_label.setObjectName("Hint")
        self.empty_label.setWordWrap(True)
        queue_layout.addWidget(self.empty_label)
        left.addWidget(queue_card, 3)

        preview_card, preview_layout = _card()
        preview_layout.addWidget(QLabel("Preview"))
        self.preview = ImagePreview()
        self.preview.set_empty_text("Select a queue entry to preview it.")
        preview_layout.addWidget(self.preview, 1)
        left.addWidget(preview_card, 2)
        content.addLayout(left, 3)

        options_card, options_layout = _card()
        options_layout.addWidget(QLabel("Export settings"))
        
        # Preset profiles for common export scenarios
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Quick presets for common export scenarios")
        self.preset_combo.addItem("Custom…", "custom")
        self.preset_combo.addItem("ID Card / Passport (JPEG, 300 DPI)", "id_card")
        self.preset_combo.addItem("High-Quality Archive (PNG, 600 DPI)", "archive")
        self.preset_combo.addItem("Web Optimized (JPEG, 150 DPI, 85%)", "web")
        self.preset_combo.addItem("Print Ready (TIFF, 300 DPI)", "print")
        self.preset_combo.addItem("PDF Document (A4, 300 DPI)", "pdf_a4")
        self.preset_combo.addItem("PDF Document (Physical Size, 300 DPI)", "pdf_physical")
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        options_layout.addWidget(self.preset_combo)
        
        self.format_combo = QComboBox()
        self.format_combo.setToolTip("Output file format")
        self.format_combo.addItems(["PNG", "JPEG", "TIFF", "PDF"])
        self.dpi_combo = QComboBox()
        self.dpi_combo.setToolTip("Output resolution in DPI (dots per inch)")
        self.dpi_combo.addItems([str(value) for value in DPI_CHOICES])
        self.dpi_combo.setEditable(True)
        self.quality_spin = QSpinBox()
        self.quality_spin.setToolTip("JPEG quality (50-100). Only applies to JPEG format")
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setValue(95)
        self.quality_spin.setSuffix(" %")
        self.dir_edit = QLineEdit(str(ctx.config.get("output_dir")))
        self.dir_edit.setToolTip("Folder where exported files will be saved")
        browse = QPushButton()
        browse.setIcon(make_icon("folder", "#475569", 16))
        browse.setToolTip("Choose output folder")
        browse.clicked.connect(self._browse_dir)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        self.template_edit = QLineEdit(str(ctx.config.get("filename_template")))
        self.template_edit.setToolTip("Filename template. Tokens: {name} {profile} {side} {date} {time} {dpi} {index}")
        self.policy_combo = QComboBox()
        self.policy_combo.setToolTip("What to do when output file already exists")
        for value, label in OVERWRITE_POLICIES:
            self.policy_combo.addItem(label, value)
        self.include_profile = QCheckBox("Add document type to filename")
        self.include_profile.setToolTip("Include the document profile name in the output filename")
        self.include_profile.setChecked(True)
        self.include_side = QCheckBox("Add front/back designation")
        self.include_side.setToolTip("Include 'front' or 'back' in filename for paired documents")
        self.include_side.setChecked(True)
        self.combine_pdf = QCheckBox("Combine all entries into one PDF")
        self.combine_pdf.setToolTip("Merge all queued images into a single multi-page PDF")
        self.page_mode_combo = QComboBox()
        self.page_mode_combo.setToolTip("PDF page size mode: fit to image, standard paper sizes, or document physical size")
        for value, label in PAGE_MODES.items():
            self.page_mode_combo.addItem(label, value)
        self.page_mode_combo.setCurrentIndex(4)
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setToolTip("Margin around the image on the PDF page in millimetres")
        self.margin_spin.setRange(0.0, 20.0)
        self.margin_spin.setSuffix(" mm")
        self.margin_spin.setDecimals(1)

        form = QFormLayout()
        form.setSpacing(9)
        form.addRow("Format", self.format_combo)
        form.addRow("DPI", self.dpi_combo)
        form.addRow("JPEG quality", self.quality_spin)
        form.addRow("Output folder", dir_row)
        form.addRow("Filename", self.template_edit)
        form.addRow("If file exists", self.policy_combo)
        form.addRow("PDF page size", self.page_mode_combo)
        form.addRow("PDF margin", self.margin_spin)
        options_layout.addLayout(form)
        options_layout.addWidget(self.include_profile)
        options_layout.addWidget(self.include_side)
        options_layout.addWidget(self.combine_pdf)
        options_layout.addStretch(1)

        action_row = QHBoxLayout()
        self.preview_pdf_button = QPushButton("Preview PDF")
        self.preview_pdf_button.clicked.connect(self._preview_pdf)
        self.export_button = QPushButton("Export")
        self.export_button.setObjectName("Primary")
        self.export_button.clicked.connect(self._start_export)
        action_row.addWidget(self.preview_pdf_button)
        action_row.addWidget(self.export_button, 1)
        options_layout.addLayout(action_row)
        content.addWidget(options_card, 2)
        layout.addLayout(content, 3)

        bottom_card, bottom_layout = _card()
        self.progress = ProgressPanel("Cancel")
        self.progress.cancelRequested.connect(self._cancel_export)
        bottom_layout.addWidget(self.progress)
        self.log = QLabel("Exported files are listed here.")
        self.log.setObjectName("Hint")
        self.log.setWordWrap(True)
        self.log.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom_layout.addWidget(self.log)
        layout.addWidget(bottom_card, 1)

        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.combine_pdf.toggled.connect(
            lambda _: self._on_format_changed(self.format_combo.currentText())
        )
        self._on_format_changed(self.format_combo.currentText())
        self._refresh_table()

    # ------------------------------------------------------------------ queue
    def _entry_from_record(self, record) -> ExportItem:
        path = None
        for candidate in (record.output_path, record.source_path):
            if candidate and Path(candidate).exists():
                path = Path(candidate)
                break
        profile = self._ctx.repository.get_profile(record.profile_id)
        return ExportItem(
            display_name=record.name or (path.stem if path else "document"),
            profile_name=record.profile_name,
            side=record.side,
            path=path,
            width_mm=profile.width_mm if profile else None,
            height_mm=profile.height_mm if profile else None,
        )

    def add_history_records(self, records: list) -> None:
        for record in records:
            self._items.append(self._entry_from_record(record))
        self._refresh_table()

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add images to the export queue", "", IMAGE_FILE_FILTER
        )
        for name in files:
            path = Path(name)
            self._items.append(ExportItem(display_name=path.stem, path=path))
        self._refresh_table()

    def _add_from_history(self) -> None:
        dialog = HistoryPickerDialog(self._ctx, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_history_records(dialog.selected_records())

    def _remove_selected(self) -> None:
        rows = sorted((index.row() for index in self.table.selectionModel().selectedRows()), reverse=True)
        for row in rows:
            if 0 <= row < len(self._items):
                self._items.pop(row)
        self._refresh_table()

    def _clear_items(self) -> None:
        self._items.clear()
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for index, item in enumerate(self._items):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.display_name))
            self.table.setItem(row, 1, QTableWidgetItem(item.profile_name or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(item.side or "—"))
            self.table.setItem(
                row, 3, QTableWidgetItem(str(item.path) if item.path else "In memory")
            )
        self.empty_label.setVisible(not self._items)
        if self._items:
            self.table.selectRow(0)
        else:
            self.preview.clear()

    def _current_row(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _update_preview(self) -> None:
        row = self._current_row()
        if row < 0 or row >= len(self._items):
            self.preview.clear()
            return
        item = self._items[row]
        try:
            self.preview.set_image(item.load())
        except (ImageLoadError, ExportError) as exc:
            self.preview.clear()
            self.log.setText(str(exc))

    # ---------------------------------------------------------------- options
    def _browse_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.dir_edit.text())
        if folder:
            self.dir_edit.setText(folder)

    def _on_format_changed(self, fmt: str) -> None:
        is_pdf = fmt == "PDF"
        self.page_mode_combo.setEnabled(is_pdf or self.combine_pdf.isChecked())
        self.preview_pdf_button.setEnabled(is_pdf or self.combine_pdf.isChecked())

    def _apply_preset(self, index: int) -> None:
        """Apply a preset export configuration."""
        if index <= 0:  # "Custom…" or no selection
            return
        preset = self.preset_combo.currentData()
        presets = {
            "id_card": {
                "format": "JPEG",
                "dpi": 300,
                "quality": 95,
                "page_mode": "fit",
            },
            "archive": {
                "format": "PNG",
                "dpi": 600,
                "quality": 100,
                "page_mode": "fit",
            },
            "web": {
                "format": "JPEG",
                "dpi": 150,
                "quality": 85,
                "page_mode": "fit",
            },
            "print": {
                "format": "TIFF",
                "dpi": 300,
                "quality": 100,
                "page_mode": "fit",
            },
            "pdf_a4": {
                "format": "PDF",
                "dpi": 300,
                "quality": 92,
                "page_mode": "a4",
            },
            "pdf_physical": {
                "format": "PDF",
                "dpi": 300,
                "quality": 92,
                "page_mode": "physical",
            },
        }
        if preset not in presets:
            return
        p = presets[preset]
        self.format_combo.setCurrentText(p["format"])
        self.dpi_combo.setCurrentText(str(p["dpi"]))
        self.quality_spin.setValue(p["quality"])
        self.page_mode_combo.setCurrentIndex(
            self.page_mode_combo.findData(p["page_mode"])
        )
        # Reset to custom so user can tweak without re-applying preset
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _options(self) -> ExportOptions:
        try:
            dpi = int(float(self.dpi_combo.currentText()))
        except ValueError:
            dpi = 300
        fmt = self.format_combo.currentText()
        return ExportOptions(
            fmt=fmt,
            dpi=max(72, min(1200, dpi)),
            quality=self.quality_spin.value(),
            output_dir=Path(self.dir_edit.text().strip() or "."),
            template=self.template_edit.text().strip() or "{name}_{profile}",
            policy=self.policy_combo.currentData(),
            include_profile=self.include_profile.isChecked(),
            include_side=self.include_side.isChecked(),
            page_mode=self.page_mode_combo.currentData(),
            margin_mm=self.margin_spin.value(),
        )

    def _valid_items(self) -> list[ExportItem]:
        return [item for item in self._items if item.image is not None or (item.path and item.path.exists())]

    def _explain_empty(self, action: str) -> str:
        """A message that says why the valid-item list is empty."""
        if self._items:
            return (
                f"None of the {len(self._items)} queued entries has a loadable image.\n"
                "Remove the broken entries or re-add them from a valid source "
                f"before {action}."
            )
        return "Add images to the queue first."

    # --------------------------------------------------------------- actions
    def _preview_pdf(self) -> None:
        items = self._valid_items()
        if not items:
            QMessageBox.information(self, "Nothing to preview", self._explain_empty("previewing"))
            return
        options = self._options()
        try:
            images = [item.load() for item in items]
            physical = None
            if items[0].width_mm and items[0].height_mm:
                physical = (items[0].width_mm, items[0].height_mm)
            data = pdf_handler.pdf_bytes_for_preview(
                images,
                page_mode=options.page_mode,
                dpi=options.dpi,
                quality=min(90, options.quality),
                physical_mm=physical,
                margin_mm=options.margin_mm,
            )
            pages = pdf_handler.render_pdf_bytes(data, dpi=110)
        except (ExportError, ImageLoadError) as exc:
            QMessageBox.critical(self, "Preview failed", str(exc))
            return
        PdfPreviewDialog(pages, "PDF preview", self).exec()

    def _start_export(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        items = self._valid_items()
        if not items:
            QMessageBox.information(
                self, "Nothing to export", self._explain_empty("exporting")
            )
            return
        options = self._options()
        combine = self.combine_pdf.isChecked() or options.normalized_format() == "PDF"
        if options.policy == OVERWRITE_REPLACE:
            answer = QMessageBox.question(
                self,
                "Replace existing files?",
                "Files with identical names in the output folder will be replaced. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._ctx.config.update(
            {
                "output_dir": str(options.output_dir),
                "default_format": options.fmt,
                "jpeg_quality": options.quality,
                "filename_template": options.template,
                "overwrite_policy": options.policy,
                "default_dpi": options.dpi,
            }
        )
        self._ctx.save_settings()

        self._worker = ExportWorker(
            self._ctx.exports, items, options, combine_pdf=combine, pdf_stem="documents", parent=self
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.exportFinished.connect(self._on_finished)
        self._cancelling = False
        self.progress.set_busy("Exporting…", cancellable=True)
        self.export_button.setEnabled(False)
        self._worker.start()

    def _cancel_export(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._cancelling = True
            self._worker.cancel()
            self.progress.set_busy("Cancelling after the current file…")

    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        self.progress.set_progress(index, total, "Exporting…", label)

    def _on_finished(self, summary: dict) -> None:
        self.export_button.setEnabled(True)
        succeeded = summary.get("succeeded", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)
        if summary.get("cancelled"):
            self.progress.set_complete(
                f"Export cancelled — {succeeded} file{'s' if succeeded != 1 else ''} written",
                "; ".join(summary.get("errors", [])[:1]),
                problem=failed > 0,
            )
        elif succeeded and not failed:
            detail = summary.get("paths", [""])[-1]
            self.progress.set_complete(
                f"Exported {succeeded} file{'s' if succeeded != 1 else ''}"
                + (f", skipped {skipped}" if skipped else ""),
                detail,
                problem=bool(skipped),
            )
        elif succeeded:
            self.progress.set_complete(
                f"Exported {succeeded}, failed {failed}"
                + (f", skipped {skipped}" if skipped else ""),
                "; ".join(summary.get("errors", [])[:2]),
                problem=True,
            )
        elif skipped and not failed:
            self.progress.set_complete(
                f"Exported 0, skipped {skipped}", "; ".join(summary.get("errors", [])[:2])
            )
        else:
            self.progress.set_complete(
                "Export failed", "; ".join(summary.get("errors", [""])[:2]), problem=True
            )
        paths = summary.get("paths", [])
        if paths:
            self.log.setText("Saved: " + "  ·  ".join(paths[:3]) + ("…" if len(paths) > 3 else ""))
        elif summary.get("errors"):
            self.log.setText(summary["errors"][0])
        if self._worker is not None:
            # The queued signal can arrive before the OS thread has fully
            # exited run(); wait briefly so the QThread object is never
            # destroyed while its thread is still running.
            self._worker.wait(5000)
        self._worker = None
