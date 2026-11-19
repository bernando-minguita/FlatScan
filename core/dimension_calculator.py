"""Millimetre / pixel / DPI conversions for corrected documents."""

from __future__ import annotations

import math
from numbers import Real

MM_PER_INCH = 25.4
MIN_DPI = 72
MAX_DPI = 1200
MAX_MM = 2000.0


class DimensionError(ValueError):
    """Raised when a physical dimension or DPI value is not usable."""


def validate_dimensions(width_mm: float, height_mm: float, dpi: float) -> None:
    if width_mm is None or height_mm is None:
        raise DimensionError("Width and height are required.")
    # Non-numeric values (strings, object-dtype scalars) must surface as the
    # typed DimensionError, not as a raw TypeError from math.isfinite. Real
    # accepts int/float and numpy scalar types; bool is rejected.
    if not isinstance(width_mm, Real) or not isinstance(height_mm, Real):
        raise DimensionError("Dimensions must be numbers.")
    if not isinstance(dpi, Real):
        raise DimensionError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")
    try:
        finite_width, finite_height = math.isfinite(width_mm), math.isfinite(height_mm)
        finite_dpi = math.isfinite(dpi)
    except TypeError:  # pragma: no cover - exotic numeric types
        raise DimensionError("Dimensions must be finite numbers.") from None
    if not finite_width or not finite_height:
        raise DimensionError("Dimensions must be finite numbers.")
    if width_mm <= 0 or height_mm <= 0:
        raise DimensionError("Width and height must be greater than zero.")
    if width_mm > MAX_MM or height_mm > MAX_MM:
        raise DimensionError(f"Dimensions above {MAX_MM:.0f} mm are not supported.")
    if not finite_dpi or dpi < MIN_DPI or dpi > MAX_DPI:
        raise DimensionError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")


def mm_to_pixels(mm: float, dpi: float) -> int:
    """Convert a physical length to pixels: (mm / 25.4) * DPI."""

    if dpi <= 0:
        raise DimensionError("DPI must be greater than zero.")
    return max(1, int(round(float(mm) / MM_PER_INCH * float(dpi))))


def pixels_to_mm(pixels: float, dpi: float) -> float:
    if dpi <= 0:
        raise DimensionError("DPI must be greater than zero.")
    return float(pixels) / float(dpi) * MM_PER_INCH


def output_pixel_size(
    width_mm: float, height_mm: float, dpi: float, rotation: int = 0
) -> tuple[int, int]:
    """Pixel size for a document, honouring quarter-turn rotation.

    ``rotation`` is applied to the corrected image, so the pixel width/height
    are swapped for 90 and 270 degrees while the physical size stays the same.
    """

    validate_dimensions(width_mm, height_mm, dpi)
    width_px = mm_to_pixels(width_mm, dpi)
    height_px = mm_to_pixels(height_mm, dpi)
    if rotation % 180 == 90:
        return height_px, width_px
    return width_px, height_px


def orientation_from_dimensions(width_mm: float, height_mm: float) -> str:
    if abs(width_mm - height_mm) < 0.01:
        return "square"
    return "landscape" if width_mm > height_mm else "portrait"


def dpi_for_pixels(pixels: float, mm: float) -> float:
    if mm <= 0:
        raise DimensionError("Physical size must be greater than zero.")
    return float(pixels) / float(mm) * MM_PER_INCH


def format_size_label(width_px: int, height_px: int, dpi: int) -> str:
    return f"{width_px} × {height_px} px  ·  {dpi} DPI"


def human_mm(value: float) -> str:
    return f"{value:.1f} mm".replace(".0 mm", " mm")


def resolution_warning(width_px: int, height_px: int, dpi: int, width_mm: float) -> str:
    """Return a warning when the source resolution cannot reach the target DPI."""

    needed = mm_to_pixels(width_mm, dpi)
    if width_px < needed:
        effective = dpi_for_pixels(width_px, width_mm)
        return (
            f"Source resolution is lower than the target: about {effective:.0f} DPI "
            f"available, {dpi} DPI requested."
        )
    return ""
