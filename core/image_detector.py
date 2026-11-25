"""High-level card detection API used by the UI, batch service and tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import corner_detection, perspective

CONFIDENCE_USABLE = 0.42


@dataclass(slots=True)
class DetectionResult:
    success: bool
    quad: np.ndarray | None = None
    confidence: float = 0.0
    strategy: str = ""
    message: str = ""
    candidates: list[corner_detection.Candidate] = field(default_factory=list)

    def as_list(self) -> list[list[float]]:
        return perspective.quad_to_list(self.quad) if self.quad is not None else []


def detect_document(image: np.ndarray, sensitivity: float = 0.5) -> DetectionResult:
    """Detect a document outline and report how trustworthy it is."""

    if image is None or image.size == 0:
        return DetectionResult(False, message="There is no image to analyse.")

    candidates = corner_detection.detect_candidates(image, sensitivity)
    if not candidates:
        return DetectionResult(
            False,
            message=(
                "No document outline was detected. Adjust the sensitivity, or place "
                "the four corners manually."
            ),
        )

    best = candidates[0]
    success = best.score >= CONFIDENCE_USABLE
    if success:
        message = f"Document detected ({best.strategy} strategy, confidence {best.score:.0%})."
    else:
        message = (
            "A possible outline was found but the confidence is low. "
            "Please verify the four corners."
        )
    return DetectionResult(
        success=success,
        quad=best.quad,
        confidence=best.score,
        strategy=best.strategy,
        message=message,
        candidates=candidates,
    )


def suggest_corners(image: np.ndarray, sensitivity: float = 0.5) -> tuple[np.ndarray, DetectionResult]:
    """Detection result, falling back to an inset frame so editing can start."""

    result = detect_document(image, sensitivity)
    if result.quad is not None:
        return perspective.order_points(result.quad), result
    return corner_detection.default_quad(image), result
