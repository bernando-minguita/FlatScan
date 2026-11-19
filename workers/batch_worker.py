"""Background batch processing with pause, resume and cancel support."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from services.batch_service import BatchConfig, BatchItemResult, process_file

logger = logging.getLogger(__name__)


class BatchWorker(QThread):
    # ``index`` is the position inside this worker's target list, not the row
    # number in the UI table (a retry processes a subset). Signals carry the
    # source path so the page can map results to the correct row.
    itemStarted = Signal(int, str)
    itemFinished = Signal(int, object)
    progressChanged = Signal(int, int)
    stateChanged = Signal(str)
    batchFinished = Signal(dict)

    def __init__(self, paths: list[Path | str], config: BatchConfig, parent=None) -> None:
        super().__init__(parent)
        self._paths = [Path(path) for path in paths]
        self._config = config
        # Events are shared between the UI thread and the worker thread
        # without manual synchronisation; pause sleeps inside the event wait.
        self._paused = threading.Event()
        self._cancelled = threading.Event()
        self._results: list[BatchItemResult] = []

    # ---------------------------------------------------------------- control
    def pause(self) -> None:
        self._paused.set()
        self.stateChanged.emit("paused")

    def resume(self) -> None:
        self._paused.clear()
        self.stateChanged.emit("running")

    def cancel(self) -> None:
        self._cancelled.set()
        self._paused.clear()
        self.stateChanged.emit("cancelling")

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def results(self) -> list[BatchItemResult]:
        return list(self._results)

    # ------------------------------------------------------------------- run
    def run(self) -> None:  # pragma: no cover - exercised through the UI
        total = len(self._paths)
        succeeded = 0
        failed = 0
        self.stateChanged.emit("running")
        for index, path in enumerate(self._paths):
            if self._cancelled.is_set():
                break
            # Blocks while paused and wakes immediately on resume/cancel.
            while self._paused.wait(0.05):
                pass
            if self._cancelled.is_set():
                break

            self.itemStarted.emit(index, str(path))
            try:
                result = process_file(path, self._config)
            except Exception as exc:  # noqa: BLE001 - one file must not stop the batch
                logger.exception("Unexpected batch failure for %s", path)
                result = BatchItemResult(
                    str(path),
                    "failed",
                    error=f"Unexpected error: {exc}",
                )

            if result.status == "success":
                succeeded += 1
            else:
                failed += 1
            self._results.append(result)
            self.itemFinished.emit(index, result)
            self.progressChanged.emit(index + 1, total)

            if result.status == "failed" and not self._config.continue_on_error:
                self.stateChanged.emit("stopped_on_error")
                break

        cancelled = self._cancelled.is_set()
        summary = {
            "total": total,
            "processed": len(self._results),
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": cancelled,
        }
        self.stateChanged.emit("cancelled" if cancelled else "finished")
        self.batchFinished.emit(summary)
