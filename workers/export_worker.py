"""Background export worker so large queues keep the interface responsive."""

from __future__ import annotations

import logging
from PySide6.QtCore import QThread, Signal

from services.export_service import ExportItem, ExportOptions, ExportService

logger = logging.getLogger(__name__)


class ExportWorker(QThread):
    progress = Signal(int, int, str)
    itemFinished = Signal(int, str, str)      # index, output path, error
    exportFinished = Signal(dict)

    def __init__(
        self,
        service: ExportService,
        items: list[ExportItem],
        options: ExportOptions,
        combine_pdf: bool = False,
        pdf_stem: str = "documents",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._items = list(items)
        self._options = options
        self._combine = combine_pdf
        self._pdf_stem = pdf_stem
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # pragma: no cover - exercised through the UI
        total = len(self._items)
        succeeded = 0
        failed = 0
        skipped = 0
        paths: list[str] = []
        errors: list[str] = []

        if self._combine:
            if self._cancelled:
                self.exportFinished.emit(
                    {"total": total, "succeeded": 0, "failed": 0, "skipped": 0, "paths": [],
                     "errors": [], "cancelled": True}
                )
                return
            self.progress.emit(0, 1, "Building PDF…")
            try:
                target = self._service.export_items_to_pdf(
                    self._items, self._options, output_stem=self._pdf_stem
                )
                if target is None:
                    errors.append(
                        "The PDF was skipped — the file already exists or the "
                        "replacement was declined."
                    )
                    skipped = 1
                else:
                    paths.append(str(target))
                    succeeded = 1
                    self.itemFinished.emit(0, str(target), "")
            except Exception as exc:  # noqa: BLE001 - reported to the UI
                logger.exception("PDF export failed")
                errors.append(str(exc))
                failed = 1
            self.progress.emit(1, 1, "PDF export finished")
        else:
            for index, item in enumerate(self._items):
                if self._cancelled:
                    break
                self.progress.emit(index, total, item.display_name)
                try:
                    result = self._service.export_item(item, self._options)
                    if result is None or result.skipped:
                        skipped += 1
                        reason = (
                            "Existing file kept — replacement declined."
                            if result is not None and result.declined
                            else "Skipped because the file already exists."
                        )
                        errors.append(f"{item.display_name}: {reason}")
                        self.itemFinished.emit(index, "", reason)
                    else:
                        succeeded += 1
                        paths.append(str(result.path))
                        self.itemFinished.emit(index, str(result.path), "")
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Export failed for %s", item.display_name)
                    failed += 1
                    errors.append(f"{item.display_name}: {exc}")
                    self.itemFinished.emit(index, "", str(exc))
                self.progress.emit(index + 1, total, item.display_name)

        self.exportFinished.emit(
            {
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "paths": paths,
                "errors": errors,
                "cancelled": self._cancelled,
            }
        )
