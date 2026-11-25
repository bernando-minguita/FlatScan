"""PDF import (render pages) and export (image to PDF) with PyMuPDF."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf

from app.constants import OVERWRITE_RENAME
from .image_exporter import ExportError, encode_for_pdf, resolve_target

MM_PER_POINT = 72.0 / 25.4


@dataclass(slots=True)
class PdfPageImage:
    index: int          # zero based page index
    image: np.ndarray   # BGR
    width: int
    height: int


def page_count(path: Path | str) -> int:
    try:
        with pymupdf.open(str(path)) as document:
            if document.needs_pass:
                raise ExportError("This PDF is password protected.")
            return document.page_count
    except (RuntimeError, OSError) as exc:
        raise ExportError(f"The PDF could not be opened: {exc}") from exc


def render_pages(
    path: Path | str,
    pages: list[int] | None = None,
    dpi: int = 200,
    max_side: int = 4000,
) -> list[PdfPageImage]:
    """Render selected pages (0-based) of a PDF to BGR images."""

    dpi = int(max(72, min(600, dpi)))
    try:
        with pymupdf.open(str(path)) as document:
            if document.needs_pass:
                raise ExportError("This PDF is password protected.")
            indices = list(range(document.page_count)) if pages is None else pages
            results: list[PdfPageImage] = []
            for index in indices:
                if index < 0 or index >= document.page_count:
                    continue
                page = document.load_page(index)
                zoom = dpi / 72.0
                rect = page.rect
                longest = max(rect.width, rect.height) * zoom
                if longest > max_side:
                    zoom *= max_side / longest
                matrix = pymupdf.Matrix(zoom, zoom)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                samples = np.frombuffer(pixmap.samples, dtype=np.uint8)
                rgb = samples.reshape(pixmap.height, pixmap.width, pixmap.n)
                image = np.ascontiguousarray(rgb[:, :, :3][:, :, ::-1])
                results.append(
                    PdfPageImage(index=index, image=image, width=image.shape[1], height=image.shape[0])
                )
            return results
    except ExportError:
        raise
    except (RuntimeError, OSError, ValueError) as exc:
        raise ExportError(f"The PDF pages could not be rendered: {exc}") from exc


PAGE_MODES = {
    "fit": "Fit to image",
    "a4": "A4 (210 × 297 mm)",
    "a5": "A5 (148 × 210 mm)",
    "letter": "US Letter (216 × 279 mm)",
    "physical": "Document physical size",
}

PAGE_SIZES_MM = {
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "letter": (215.9, 279.4),
}


def _page_size_points(
    mode: str,
    image_width: int,
    image_height: int,
    dpi: int,
    physical_mm: tuple[float, float] | None,
) -> tuple[float, float]:
    if mode in PAGE_SIZES_MM:
        width_mm, height_mm = PAGE_SIZES_MM[mode]
        landscape = image_width > image_height
        if landscape:
            width_mm, height_mm = max(width_mm, height_mm), min(width_mm, height_mm)
        else:
            width_mm, height_mm = min(width_mm, height_mm), max(width_mm, height_mm)
        return width_mm * MM_PER_POINT, height_mm * MM_PER_POINT
    if mode == "physical" and physical_mm:
        width_mm, height_mm = physical_mm
        landscape = image_width > image_height
        if landscape != (width_mm > height_mm):
            width_mm, height_mm = height_mm, width_mm
        return width_mm * MM_PER_POINT, height_mm * MM_PER_POINT
    return (
        image_width / float(dpi) * 72.0,
        image_height / float(dpi) * 72.0,
    )


def build_pdf(
    output_path: Path | str,
    images: list[np.ndarray],
    page_mode: str = "fit",
    dpi: int = 300,
    quality: int = 92,
    physical_mm: tuple[float, float] | None = None,
    policy: str = OVERWRITE_RENAME,
    margin_mm: float = 0.0,
    metadata: dict | None = None,
) -> Path | None:
    """Create a PDF from corrected images, one page per image.

    Returns ``None`` when the overwrite policy skipped an existing file.
    """

    if not images:
        raise ExportError("There are no images to place in the PDF.")
    if page_mode not in PAGE_MODES:
        page_mode = "fit"

    target = Path(output_path)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")
    resolved = resolve_target(target, policy)
    if resolved is None:
        return None

    resolved.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    temporary = resolved.with_name(resolved.name + ".part")
    try:
        for image in images:
            if image is None or image.size == 0:
                # Silently dropping a page would produce a document that looks
                # successful but is missing a side.
                raise ExportError("An image in the PDF export is empty.")
            height, width = image.shape[:2]
            page_width, page_height = _page_size_points(page_mode, width, height, dpi, physical_mm)
            page = document.new_page(width=page_width, height=page_height)
            margin = max(0.0, margin_mm) * MM_PER_POINT
            available_w = max(1.0, page_width - margin * 2)
            available_h = max(1.0, page_height - margin * 2)
            scale = min(available_w / width, available_h / height)
            draw_w, draw_h = width * scale, height * scale
            left = (page_width - draw_w) / 2.0
            top = (page_height - draw_h) / 2.0
            rect = pymupdf.Rect(left, top, left + draw_w, top + draw_h)
            stream = encode_for_pdf(image, quality)
            page.insert_image(rect, stream=stream, keep_proportion=True)
        if metadata:
            clean = {str(k): str(v) for k, v in metadata.items() if v}
            document.set_metadata(clean)
        # Write beside the target then swap, so a failure never leaves a
        # truncated PDF under the real name.
        document.save(str(temporary), deflate=True, garbage=3)
    except (RuntimeError, OSError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ExportError(
            f"Could not create the PDF. Check the output folder and free disk space.\n{exc}"
        ) from exc
    finally:
        document.close()
    try:
        temporary.replace(resolved)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ExportError(
            f"The PDF could not be written. Check the output folder and permissions.\n{exc}"
        ) from exc
    return resolved


def build_pdf_from_files(
    output_path: Path | str,
    image_paths: list[Path | str],
    page_mode: str = "fit",
    dpi: int = 300,
    quality: int = 92,
    physical_mm: tuple[float, float] | None = None,
    policy: str = OVERWRITE_RENAME,
    margin_mm: float = 0.0,
) -> Path | None:
    from .image_loader import load_image

    images = [load_image(path).image for path in image_paths]
    return build_pdf(
        output_path,
        images,
        page_mode=page_mode,
        dpi=dpi,
        quality=quality,
        physical_mm=physical_mm,
        policy=policy,
        margin_mm=margin_mm,
    )


def pdf_bytes_for_preview(
    images: list[np.ndarray],
    page_mode: str = "fit",
    dpi: int = 300,
    quality: int = 88,
    physical_mm: tuple[float, float] | None = None,
    margin_mm: float = 0.0,
) -> bytes:
    """Build a PDF in memory for the export preview."""

    if not images:
        raise ExportError("There are no images to preview.")
    if page_mode not in PAGE_MODES:
        page_mode = "fit"
    document = pymupdf.open()
    try:
        for image in images:
            if image is None or image.size == 0:
                raise ExportError("An image in the PDF preview is empty.")
            height, width = image.shape[:2]
            page_width, page_height = _page_size_points(page_mode, width, height, dpi, physical_mm)
            page = document.new_page(width=page_width, height=page_height)
            margin = max(0.0, margin_mm) * MM_PER_POINT
            scale = min(
                max(1.0, page_width - margin * 2) / width,
                max(1.0, page_height - margin * 2) / height,
            )
            draw_w, draw_h = width * scale, height * scale
            rect = pymupdf.Rect(
                (page_width - draw_w) / 2.0,
                (page_height - draw_h) / 2.0,
                (page_width + draw_w) / 2.0,
                (page_height + draw_h) / 2.0,
            )
            page.insert_image(rect, stream=encode_for_pdf(image, quality), keep_proportion=True)
        data = document.tobytes(deflate=True)
    finally:
        # Always release the native PyMuPDF document, even when encoding a
        # page fails part-way through.
        document.close()
    return data


def render_pdf_bytes(data: bytes, dpi: int = 150) -> list[np.ndarray]:
    """Render in-memory PDF bytes, used by the preview panel."""

    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            results: list[np.ndarray] = []
            for page in document:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
                samples = np.frombuffer(pixmap.samples, dtype=np.uint8)
                rgb = samples.reshape(pixmap.height, pixmap.width, pixmap.n)
                results.append(np.ascontiguousarray(rgb[:, :, :3][:, :, ::-1]))
            return results
    except (RuntimeError, ValueError) as exc:
        raise ExportError(f"Could not render the PDF preview: {exc}") from exc


def png_bytes(image: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(_rgb_copy(image)).save(buffer, format="PNG")
    return buffer.getvalue()


def _rgb_copy(image: np.ndarray) -> np.ndarray:
    """Convert a BGR/BGRA/grayscale array to a 2-D or RGB copy for Pillow."""

    if image is None or image.size == 0:
        raise ExportError("There is no image to convert.")
    if image.ndim == 2:
        return np.ascontiguousarray(image)
    if image.shape[2] == 4:
        image = image[:, :, :3]
    return np.ascontiguousarray(image[:, :, ::-1])
