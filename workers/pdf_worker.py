"""PDF preview/build workers."""

from __future__ import annotations

import logging
from pathlib import Path

from core import pdf_handler
from .image_worker import LatestTaskWorker

logger = logging.getLogger(__name__)


def build_pdf_task(payload: dict) -> dict:
    """Build a PDF from already-prepared images in a worker thread."""

    path = pdf_handler.build_pdf(
        payload["output_path"],
        payload["images"],
        page_mode=payload.get("page_mode", "fit"),
        dpi=int(payload.get("dpi", 300)),
        quality=int(payload.get("quality", 92)),
        physical_mm=payload.get("physical_mm"),
        policy=payload.get("policy", "rename"),
        margin_mm=float(payload.get("margin_mm", 0.0)),
        metadata=payload.get("metadata"),
    )
    return {"path": str(path) if path else ""}


def preview_pdf_task(payload: dict) -> dict:
    """Render a PDF preview using the export settings."""

    data = pdf_handler.pdf_bytes_for_preview(
        payload["images"],
        page_mode=payload.get("page_mode", "fit"),
        dpi=int(payload.get("dpi", 300)),
        quality=int(payload.get("quality", 88)),
        physical_mm=payload.get("physical_mm"),
        margin_mm=float(payload.get("margin_mm", 0.0)),
    )
    pages = pdf_handler.render_pdf_bytes(data, dpi=int(payload.get("preview_dpi", 120)))
    return {"pages": pages, "pdf_bytes": data}


class PdfRenderWorker(LatestTaskWorker):
    def __init__(self, parent=None) -> None:
        from .image_worker import pdf_render_task

        super().__init__(pdf_render_task, parent)


def save_pdf_bytes(path: Path | str, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target then swap, matching build_pdf's atomic pattern.
    temporary = target.with_name(target.name + ".part")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target
