"""Raster image export with DPI metadata and conflict-safe writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.constants import (
    OVERWRITE_RENAME,
    OVERWRITE_REPLACE,
    OVERWRITE_SKIP,
    RASTER_FORMATS,
)

FORMAT_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tif", "PDF": ".pdf"}
FORMAT_LABELS = {
    "PNG": "PNG image",
    "JPEG": "JPEG image",
    "TIFF": "TIFF image",
    "PDF": "PDF document",
}


class ExportError(Exception):
    """User-facing export problem."""


@dataclass
class SaveResult:
    path: Path
    skipped: bool = False
    replaced: bool = False
    declined: bool = False  # the user declined to replace an existing file


def ensure_format(fmt: str) -> str:
    fmt = (fmt or "PNG").upper()
    if fmt not in RASTER_FORMATS + ("PDF",):
        raise ExportError(f"Unsupported export format: {fmt}")
    return fmt


def same_path(first: Path | str, second: Path | str) -> bool:
    """True when two paths refer to the same file (case-insensitive on Windows)."""

    try:
        return Path(first).resolve() == Path(second).resolve()
    except OSError:  # pragma: no cover - unusual filesystem failure
        return str(first).lower() == str(second).lower()


def unique_path(path: Path) -> Path:
    """Return a non-existing path by appending ``_1``, ``_2`` ..."""

    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ExportError(f"Could not find a free filename for {path.name}.")


def resolve_target(path: Path, policy: str) -> Path | None:
    """Apply the overwrite policy. ``None`` means skip this file."""

    if not path.exists():
        return path
    if policy == OVERWRITE_RENAME:
        return unique_path(path)
    if policy == OVERWRITE_SKIP:
        return None
    if policy == OVERWRITE_REPLACE:
        return path
    return unique_path(path)


def _pil_from_bgr(image: np.ndarray) -> Image.Image:
    if image is None or image.size == 0:
        raise ExportError("There is no image to export.")
    array = image
    if array.ndim == 2:
        return Image.fromarray(array)
    if array.shape[2] == 4:
        array = array[:, :, :3]
    return Image.fromarray(np.ascontiguousarray(array[:, :, ::-1]))


def _discard(path: Path) -> None:
    """Remove a staging file, ignoring failures (best-effort cleanup)."""

    try:
        path.unlink()
    except OSError:
        pass


def save_raster(
    path: Path | str,
    image: np.ndarray,
    fmt: str,
    dpi: int = 300,
    quality: int = 95,
    policy: str = OVERWRITE_RENAME,
) -> SaveResult:
    """Write a raster file and embed DPI metadata where the format allows.

    The encoded image is written to a ``.part`` staging file first and then
    moved into place, so a failure part-way through (disk full, crash) never
    truncates a previously exported file under the "replace" policy.
    """

    fmt = ensure_format(fmt)
    if fmt == "PDF":
        raise ExportError("Use the PDF handler to create PDF documents.")
    target = Path(path)
    if target.suffix.lower() != FORMAT_EXTENSIONS[fmt]:
        target = target.with_suffix(FORMAT_EXTENSIONS[fmt])

    resolved = resolve_target(target, policy)
    if resolved is None:
        return SaveResult(path=target, skipped=True, replaced=False)
    replaced = resolved == target and target.exists()

    target.parent.mkdir(parents=True, exist_ok=True)
    pil_image = _pil_from_bgr(image)
    quality = int(max(50, min(100, quality)))
    dpi = int(max(72, dpi))
    options: dict = {"dpi": (dpi, dpi)}
    staging = resolved.with_name(resolved.name + ".part")
    try:
        if fmt == "JPEG":
            options.update(quality=quality, subsampling=0, optimize=True)
            pil_image.convert("RGB").save(staging, format="JPEG", **options)
        elif fmt == "PNG":
            options.update(compress_level=6)
            pil_image.save(staging, format="PNG", **options)
        else:  # TIFF
            options.update(compression="tiff_lzw")
            pil_image.save(staging, format="TIFF", **options)
    except OSError as exc:
        _discard(staging)
        raise ExportError(
            f"Could not write {resolved.name}. Check disk space and folder permissions.\n{exc}"
        ) from exc
    except Exception:
        _discard(staging)
        raise
    try:
        staging.replace(resolved)
    except OSError as exc:
        _discard(staging)
        raise ExportError(
            f"Could not finalise {resolved.name}. Check folder permissions.\n{exc}"
        ) from exc
    return SaveResult(path=resolved, replaced=replaced)


def read_dpi(path: Path | str) -> tuple[float, float] | None:
    """Read embedded DPI metadata (used by tests and the export preview)."""

    try:
        with Image.open(path) as pil_image:
            dpi = pil_image.info.get("dpi")
            if dpi:
                return float(dpi[0]), float(dpi[1])
    except (OSError, ValueError):
        return None
    return None


def encode_for_pdf(image: np.ndarray, quality: int = 92) -> bytes:
    """Encode an image as JPEG bytes for embedding in a PDF."""

    import io

    pil_image = _pil_from_bgr(image)
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    buffer = io.BytesIO()
    pil_image.save(buffer, format="JPEG", quality=int(max(60, min(100, quality))))
    return buffer.getvalue()
