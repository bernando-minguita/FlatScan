"""The non-destructive correction pipeline shared by studio, batch and PDF import."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import dimension_calculator, enhancement, orientation, perspective, quality_analyzer


@dataclass
class ProcessingSettings:
    width_mm: float = 85.6
    height_mm: float = 54.0
    dpi: int = 300
    rotation: int = 0                 # 0/90/180/270 clockwise, applied after warping
    auto_orientation: bool = False
    interpolation: str = "Cubic"
    enhancement: dict = field(default_factory=dict)
    apply_enhancement: bool = True

    def expected_landscape(self) -> bool | None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            return None
        if abs(self.width_mm - self.height_mm) < 0.01:
            return None
        return self.width_mm > self.height_mm

    def target_size(self, rotation: int | None = None) -> tuple[int, int]:
        return dimension_calculator.output_pixel_size(
            self.width_mm,
            self.height_mm,
            self.dpi,
            self.rotation if rotation is None else rotation,
        )


@dataclass
class ProcessedDocument:
    base_image: np.ndarray           # warped + rotated, no enhancement
    image: np.ndarray                # final result (base + enhancement)
    corners: np.ndarray
    rotation: int
    size: tuple[int, int]
    settings: ProcessingSettings
    quality: quality_analyzer.QualityReport | None = None

    @property
    def width(self) -> int:
        return int(self.size[0])

    @property
    def height(self) -> int:
        return int(self.size[1])


def oriented_quad(quad: np.ndarray, settings: "ProcessingSettings") -> np.ndarray:
    """Align the sampled outline with the profile's expected orientation.

    If the photo shows the card sideways, the short edge would be mapped to the
    output width and the result would be stretched. Rotating the corner order by
    one step maps the long edge to the width instead, keeping the document's
    physical aspect ratio without resampling twice.
    """

    expected_landscape = settings.expected_landscape()
    if not settings.auto_orientation or expected_landscape is None:
        return quad
    try:
        ratio = perspective.quad_aspect_ratio(quad)
    except perspective.InvalidQuadrilateral:
        return quad
    if abs(ratio - 1.0) < 0.06:
        return quad
    if (ratio > 1.0) != expected_landscape:
        return np.roll(quad, -1, axis=0).astype(np.float32)
    return quad


def correct_document(
    image: np.ndarray,
    corners,
    settings: ProcessingSettings,
    analyze_quality: bool = True,
) -> ProcessedDocument:
    """Warp the source to physical size, rotate it and enhance a copy."""

    if image is None or image.size == 0:
        raise ValueError("No source image supplied.")
    quad = perspective.order_points(corners)
    if not perspective.is_valid_quad(quad, min_area=200.0):
        raise perspective.InvalidQuadrilateral(
            "The four corners do not form a valid document outline."
        )

    # Warp once into the document's natural pixel size, then apply rotation.
    sampling_quad = oriented_quad(quad, settings)
    width_px, height_px = settings.target_size(0)
    base = perspective.warp_perspective(
        image,
        sampling_quad,
        width_px,
        height_px,
        interpolation=settings.interpolation,
        # Preserve the auto-orientation roll: re-ordering here would keep the
        # short edge as the output width and squeeze a sideways document.
        order=False,
    )
    rotation = orientation.normalize_rotation(settings.rotation)
    if rotation:
        base = orientation.rotate_image(base, rotation)
    width_px, height_px = base.shape[1], base.shape[0]

    result = (
        enhancement.apply_enhancements(base, settings.enhancement)
        if settings.apply_enhancement
        else base.copy()
    )
    report = (
        quality_analyzer.analyze_quality(
            result,
            required_px=(width_px, height_px),
            source_size=(image.shape[1], image.shape[0]),
        )
        if analyze_quality
        else None
    )
    return ProcessedDocument(
        base_image=base,
        image=result,
        corners=quad,
        rotation=rotation,
        size=(width_px, height_px),
        settings=settings,
        quality=report,
    )


def process_document(
    image: np.ndarray,
    settings: ProcessingSettings,
    sensitivity: float = 0.5,
) -> tuple[ProcessedDocument, object]:
    """Detect then correct, returning both the result and detection info."""

    from .image_detector import suggest_corners

    quad, detection = suggest_corners(image, sensitivity)
    document = correct_document(image, quad, settings, analyze_quality=False)
    document.quality = quality_analyzer.analyze_quality(
        document.image,
        required_px=document.size,
        detection_confidence=detection.confidence,
        source_size=(image.shape[1], image.shape[0]),
    )
    return document, detection
