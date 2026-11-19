"""Background workers for the interactive editor.

Only the newest request is processed; intermediate requests (produced while a
slider is being dragged) are dropped, which keeps the UI responsive without
spawning a thread per event.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal

from core import image_detector, pipeline, quality_analyzer

logger = logging.getLogger(__name__)


class LatestTaskWorker(QThread):
    resultReady = Signal(int, object)
    taskFailed = Signal(int, str)

    def __init__(self, task: Callable[[Any], Any], parent=None) -> None:
        super().__init__(parent)
        self._task = task
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._pending: tuple[int, Any] | None = None
        self._stopping = False

    def submit(self, token: int, payload: Any) -> None:
        with QMutexLocker(self._mutex):
            self._pending = (int(token), payload)
            self._condition.wakeAll()

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stopping = True
            self._condition.wakeAll()

    def run(self) -> None:  # pragma: no cover - threading behaviour
        while True:
            with QMutexLocker(self._mutex):
                while self._pending is None and not self._stopping:
                    self._condition.wait(self._mutex, 250)
                if self._stopping:
                    return
                token, payload = self._pending
                self._pending = None
            try:
                result = self._task(payload)
            except Exception as exc:  # noqa: BLE001 - reported to the UI
                logger.error("Background task failed: %s\n%s", exc, traceback.format_exc())
                self.taskFailed.emit(token, str(exc))
                continue
            self.resultReady.emit(token, result)


# --------------------------------------------------------------------- tasks
def detect_task(payload: dict) -> dict:
    image = payload["image"]
    sensitivity = float(payload.get("sensitivity", 0.5))
    quad, result = image_detector.suggest_corners(image, sensitivity)
    return {
        "quad": [[float(x), float(y)] for x, y in quad],
        "success": result.success,
        "confidence": result.confidence,
        "strategy": result.strategy,
        "message": result.message,
    }


def render_task(payload: dict) -> dict:
    """Build the corrected preview and quality report off the UI thread."""

    image = payload["image"]
    corners = payload["corners"]
    settings: pipeline.ProcessingSettings = payload["settings"]
    document = pipeline.correct_document(image, corners, settings, analyze_quality=False)
    quality = None
    if payload.get("analyze", True):
        report: quality_analyzer.QualityReport = quality_analyzer.analyze_quality(
            document.image,
            required_px=document.size,
            detection_confidence=payload.get("confidence"),
            source_size=(image.shape[1], image.shape[0]),
        )
        quality = {
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "title": issue.title,
                    "message": issue.message,
                }
                for issue in report.issues
            ],
            "blur": report.blur_score,
            "brightness": report.brightness,
        }
    return {
        "base": document.base_image,
        "image": document.image,
        "size": document.size,
        "rotation": document.rotation,
        "quality": quality,
    }


def pdf_render_task(payload: dict) -> dict:
    from core import pdf_handler

    pages = pdf_handler.render_pages(
        payload["path"], payload.get("pages"), dpi=int(payload.get("dpi", 200))
    )
    return {
        "pages": [
            {"index": page.index, "image": page.image, "width": page.width, "height": page.height}
            for page in pages
        ]
    }
