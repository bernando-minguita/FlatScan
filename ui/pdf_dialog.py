"""PDF page selection and import to the correction studio."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from core import pdf_handler
from core.image_exporter import ExportError, save_raster
from ui.widgets.image_preview import ImagePreview


class PdfImportDialog(QDialog):
    """Choose pages and a render resolution, then save them for editing."""

    def __init__(self, pdf_path: Path | str, temp_dir: Path | str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import pages from PDF")
        self.resize(860, 620)
        self._pdf_path = Path(pdf_path)
        self._temp_dir = Path(temp_dir)
        self._imported: list[Path] = []
        self._previewed_index = -1

        try:
            self._page_count = pdf_handler.page_count(self._pdf_path)
        except ExportError as exc:
            QMessageBox.critical(self, "Cannot open PDF", str(exc))
            self._page_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(
            f"{self._pdf_path.name} — {self._page_count} page{'s' if self._page_count != 1 else ''}"
        )
        header.setObjectName("SectionTitle")
        layout.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.pages = QListWidget()
        self.pages.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for index in range(self._page_count):
            item = QListWidgetItem(f"Page {index + 1}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index == 0 else Qt.CheckState.Unchecked)
            self.pages.addItem(item)
        self.pages.itemSelectionChanged.connect(self._update_preview)
        left.addWidget(QLabel("Pages"))
        left.addWidget(self.pages, 1)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("Render resolution"))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["100", "150", "200", "300", "400"])
        self.dpi_combo.setCurrentText("200")
        dpi_row.addWidget(self.dpi_combo)
        dpi_row.addStretch(1)
        left.addLayout(dpi_row)
        select_all = QDialogButtonBox()
        all_button = select_all.addButton("Select all", QDialogButtonBox.ButtonRole.ActionRole)
        none_button = select_all.addButton("Select none", QDialogButtonBox.ButtonRole.ActionRole)
        all_button.clicked.connect(lambda: self._set_all(True))
        none_button.clicked.connect(lambda: self._set_all(False))
        left.addWidget(select_all)
        content.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel("Preview"))
        self.preview = ImagePreview()
        self.preview.set_empty_text("Select a page to preview it.")
        right.addWidget(self.preview, 1)
        hint = QLabel(
            "Imported pages are written to the temporary folder and opened in the "
            "Correction Studio. Extra pages are queued in Batch Processing."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        right.addWidget(hint)
        content.addLayout(right, 3)
        layout.addLayout(content, 1)

        buttons = QDialogButtonBox()
        import_button = buttons.addButton("Import selected", QDialogButtonBox.ButtonRole.AcceptRole)
        import_button.setObjectName("Primary")
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self._page_count:
            self.pages.setCurrentRow(0)
            self._preview(0)

    # ----------------------------------------------------------------- helpers
    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.pages.count()):
            self.pages.item(row).setCheckState(state)

    def _checked_pages(self) -> list[int]:
        pages: list[int] = []
        for row in range(self.pages.count()):
            item = self.pages.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                pages.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return pages

    def _update_preview(self) -> None:
        row = self.pages.currentRow()
        if row >= 0 and row != self._previewed_index:
            self._preview(row)

    def _preview(self, row: int) -> None:
        di = self.pages.item(row)
        if di is None:
            return
        index = int(di.data(Qt.ItemDataRole.UserRole))
        dpi = int(self.dpi_combo.currentText())
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rendered = pdf_handler.render_pages(self._pdf_path, [index], dpi=min(dpi, 200))
        except ExportError as exc:
            self.preview.set_empty_text(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - corrupt PDFs raise varied errors
            self.preview.set_empty_text(f"The page could not be rendered: {exc}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        if rendered:
            self.preview.set_image(rendered[0].image)
            self._previewed_index = row

    # ------------------------------------------------------------------ import
    def _import(self) -> None:
        pages = self._checked_pages()
        if not pages:
            QMessageBox.information(self, "No pages selected", "Select at least one page to import.")
            return
        dpi = int(self.dpi_combo.currentText())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rendered = pdf_handler.render_pages(self._pdf_path, pages, dpi=dpi)
            if not rendered:
                raise ExportError("The selected pages could not be rendered.")
            folder = self._temp_dir / f"pdf_{uuid.uuid4().hex[:8]}"
            folder.mkdir(parents=True, exist_ok=True)
            saved: list[Path] = []
            for page in rendered:
                target = folder / f"{self._pdf_path.stem}_page{page.index + 1}.png"
                result = save_raster(target, page.image, "PNG", dpi=72)
                saved.append(result.path)
            self._imported = saved
        except (ExportError, OSError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - corrupt PDFs raise varied errors
            QMessageBox.critical(self, "Import failed", f"The PDF could not be read: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.accept()

    def imported_paths(self) -> list[Path]:
        return list(self._imported)
