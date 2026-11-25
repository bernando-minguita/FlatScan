"""Objective image quality checks with plain-language warnings."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

_SEVERITY_ORDER = {INFO: 0, WARNING: 1, CRITICAL: 2}


@dataclass(slots=True)
class QualityIssue:
    code: str
    severity: str
    title: str
    message: str

    @property
    def is_problem(self) -> bool:
        return self.severity in (WARNING, CRITICAL)


@dataclass(slots=True)
class QualityReport:
    issues: list[QualityIssue]
    blur_score: float
    brightness: float
    resolution: tuple[int, int]

    @property
    def problems(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.is_problem]

    @property
    def worst_severity(self) -> str:
        if not self.issues:
            return INFO
        return max((i.severity for i in self.issues), key=lambda s: _SEVERITY_ORDER[s])


def analyze_quality(
    image: np.ndarray,
    required_px: tuple[int, int] | None = None,
    detection_confidence: float | None = None,
    source_size: tuple[int, int] | None = None,
) -> QualityReport:
    """Run the quality checks and return readable issues.

    The checks report measurable facts (sharpness, clipping, exposure). They
    never promise that a degraded photo can be restored. ``source_size`` (the
    original photo's dimensions) enables the below-target check: comparing the
    corrected output against its own target would be meaningless, since the
    output already matches it by construction.
    """

    issues: list[QualityIssue] = []
    if image is None or image.size == 0:
        return QualityReport(
            [QualityIssue("empty", CRITICAL, "No image", "There is no image to analyse.")],
            0.0,
            0.0,
            (0, 0),
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]

    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur < 45:
        issues.append(
            QualityIssue(
                "blur",
                CRITICAL,
                "Image looks very blurred",
                "Fine text may be unreadable. Sharpening cannot recover detail that "
                "was never captured — retake the photo if it matters.",
            )
        )
    elif blur < 110:
        issues.append(
            QualityIssue(
                "soft",
                WARNING,
                "Image is slightly soft",
                "The capture is not perfectly sharp. Check text legibility before "
                "archiving the result.",
            )
        )

    mean_brightness = float(gray.mean())
    dark_ratio = float((gray < 40).mean())
    bright_ratio = float((gray > 245).mean())

    if mean_brightness < 55 or dark_ratio > 0.45:
        issues.append(
            QualityIssue(
                "underexposed",
                WARNING,
                "Underexposed image",
                "The photo is dark. Brightness and gamma correction can help, but "
                "noise will increase in the shadows.",
            )
        )
    elif mean_brightness > 205 or bright_ratio > 0.30:
        issues.append(
            QualityIssue(
                "overexposed",
                WARNING,
                "Overexposed image",
                "Large parts of the image are near-white. Detail lost to clipping "
                "cannot be recovered.",
            )
        )

    # Strong shadow: compare mean of the darkest and brightest columns/rows.
    col_means = gray.mean(axis=0)
    row_means = gray.mean(axis=1)
    light_side = float(max(col_means.max(), row_means.max()))
    dark_side = float(min(col_means.min(), row_means.min()))
    if light_side - dark_side > 85:
        issues.append(
            QualityIssue(
                "shadow",
                WARNING,
                "Strong shadow or uneven lighting",
                "One side of the document is much darker than the other. "
                "Automatic white balance and brightness may reduce the difference.",
            )
        )

    glare_ratio = float((gray > 250).mean())
    if glare_ratio > 0.04:
        issues.append(
            QualityIssue(
                "glare",
                CRITICAL if glare_ratio > 0.12 else WARNING,
                "Glare or reflection detected",
                f"{glare_ratio * 100:.1f}% of the image is fully clipped to white. "
                "Reflections hide printed information permanently.",
            )
        )

    if width * height < 500_000:
        issues.append(
            QualityIssue(
                "low_resolution",
                WARNING,
                "Low image resolution",
                f"The source is only {width} × {height} px. Print quality at 300 DPI "
                "will require upscaling.",
            )
        )

    if required_px and source_size:
        req_w, req_h = required_px
        src_w, src_h = source_size
        if src_w < req_w * 0.75 or src_h < req_h * 0.75:
            issues.append(
                QualityIssue(
                    "below_target",
                    WARNING,
                    "Source smaller than the output size",
                    f"The source photo is only {src_w} × {src_h} px but the output size is "
                    f"{req_w} × {req_h} px. The image will be interpolated; "
                    "upscaling cannot add detail.",
                )
            )

    if detection_confidence is not None and detection_confidence < 0.45:
        issues.append(
            QualityIssue(
                "boundary",
                WARNING,
                "Uncertain card boundary",
                "Automatic detection confidence is low. Check the four corners in the "
                "Corner Adjustment tab and move them if needed.",
            )
        )

    if not issues:
        issues.append(
            QualityIssue(
                "ok",
                INFO,
                "No quality problems detected",
                "Sharpness, exposure and resolution are within the expected range.",
            )
        )

    return QualityReport(issues, blur, mean_brightness, (width, height))
