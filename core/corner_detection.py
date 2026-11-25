"""Document boundary detection.

Several independent strategies propose candidate quadrilaterals. Every
candidate is scored using area, rectangularity, convexity, edge strength,
corner geometry, background contrast and plausible document aspect ratios.
The best candidate wins — the largest rectangle is *not* assumed to be the
document.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.constants import COMMON_ASPECT_RATIOS
from . import perspective

DETECTION_MAX_SIDE = 1280


@dataclass(slots=True)
class Candidate:
    quad: np.ndarray               # ordered in original image coordinates
    score: float = 0.0
    strategy: str = ""
    metrics: dict = field(default_factory=dict)

    def as_list(self) -> list[list[float]]:
        return perspective.quad_to_list(self.quad)


def _resize_for_detection(image: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= DETECTION_MAX_SIDE:
        return image, 1.0
    scale = DETECTION_MAX_SIDE / float(longest)
    resized = cv2.resize(
        image,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _enhanced_gray(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    equalized = clahe.apply(gray)
    return cv2.bilateralFilter(equalized, 9, 45, 45)


def _auto_canny(gray: np.ndarray, sigma: float = 0.33) -> np.ndarray:
    median = float(np.median(gray))
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))
    if upper <= lower + 10:
        lower, upper = 40, 120
    return cv2.Canny(gray, lower, upper)


def _quads_from_mask(mask: np.ndarray, sensitivity: float) -> list[np.ndarray]:
    """Approximate contour candidates from a binary edge/region mask."""

    kernel = np.ones((3, 3), np.uint8)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    min_area = (0.01 + 0.06 * (1.0 - sensitivity)) * mask.shape[0] * mask.shape[1]
    quads: list[np.ndarray] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:25]:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 40:
            continue
        for epsilon in (0.015, 0.02, 0.03, 0.04, 0.06):
            approx = cv2.approxPolyDP(contour, epsilon * perimeter, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
                if perspective.is_valid_quad(quad, min_area=min_area):
                    quads.append(quad)
                break
        else:
            # Near-rectangular blob: use the minimum-area rectangle as a hint.
            if area > min_area * 4:
                box = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
                hull_area = cv2.contourArea(cv2.convexHull(contour))
                fill_ratio = area / max(hull_area, 1.0)
                if fill_ratio > 0.86 and perspective.is_valid_quad(box, min_area=min_area):
                    quads.append(box)
    return quads


def _line_intersection(line_a: np.ndarray, line_b: np.ndarray) -> tuple[float, float] | None:
    x1, y1, x2, y2 = map(float, line_a)
    x3, y3, x4, y4 = map(float, line_b)
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-6:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denominator
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denominator
    return float(px), float(py)


def _quads_from_lines(edges: np.ndarray, sensitivity: float) -> list[np.ndarray]:
    height, width = edges.shape[:2]
    min_length = int(min(height, width) * (0.18 + 0.12 * (1.0 - sensitivity)))
    threshold = int(40 + 60 * (1.0 - sensitivity))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=threshold,
        minLineLength=min_length,
        maxLineGap=int(min_length * 0.25),
    )
    if lines is None or len(lines) < 4:
        return []

    horizontal: list[tuple[float, np.ndarray]] = []
    vertical: list[tuple[float, np.ndarray]] = []
    for raw in lines.reshape(-1, 4):
        x1, y1, x2, y2 = map(float, raw)
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        length = float(np.hypot(x2 - x1, y2 - y1))
        if angle < 40 or angle > 140:
            horizontal.append((length, raw.astype(np.float32)))
        elif 50 < angle < 130:
            vertical.append((length, raw.astype(np.float32)))
    if len(horizontal) < 2 or len(vertical) < 2:
        return []

    horizontal.sort(key=lambda item: item[0], reverse=True)
    vertical.sort(key=lambda item: item[0], reverse=True)
    top_lines = horizontal[:6]
    bottom_lines = horizontal[:6]
    left_lines = vertical[:6]
    right_lines = vertical[:6]

    def midpoint_x(line):
        return (line[1][0] + line[1][2]) / 2.0

    def midpoint_y(line):
        return (line[1][1] + line[1][3]) / 2.0

    top = min(top_lines, key=midpoint_y)
    bottom = max(bottom_lines, key=midpoint_y)
    left = min(left_lines, key=midpoint_x)
    right = max(right_lines, key=midpoint_x)

    corners = [
        _line_intersection(top[1], left[1]),
        _line_intersection(top[1], right[1]),
        _line_intersection(bottom[1], right[1]),
        _line_intersection(bottom[1], left[1]),
    ]
    if any(corner is None for corner in corners):
        return []
    quad = np.array(corners, dtype=np.float32)
    margin = 0.05 * max(height, width)
    if (
        quad[:, 0].min() < -margin
        or quad[:, 1].min() < -margin
        or quad[:, 0].max() > width + margin
        or quad[:, 1].max() > height + margin
    ):
        return []
    quad[:, 0] = np.clip(quad[:, 0], 0, width - 1)
    quad[:, 1] = np.clip(quad[:, 1], 0, height - 1)
    return [quad] if perspective.is_valid_quad(quad) else []


def _edge_support(image: np.ndarray, quad: np.ndarray) -> float:
    """Mean gradient magnitude sampled along the four quad edges."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    height, width = gray.shape[:2]
    values: list[float] = []
    for index in range(4):
        start = quad[index]
        end = quad[(index + 1) % 4]
        samples = 60
        for t in np.linspace(0.02, 0.98, samples):
            x = int(round(start[0] + (end[0] - start[0]) * t))
            y = int(round(start[1] + (end[1] - start[1]) * t))
            if 0 <= x < width and 0 <= y < height:
                values.append(float(magnitude[y, x]))
    if not values:
        return 0.0
    return float(np.mean(values))


def _background_contrast(image: np.ndarray, quad: np.ndarray) -> float:
    """Difference between the inside and the immediate outside of the document."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [quad.astype(np.int32)], 255)
    kernel = np.ones((25, 25), np.uint8)
    outside = cv2.dilate(mask, kernel)
    outside_band = cv2.subtract(outside, mask)
    inside_pixels = gray[mask > 0]
    outside_pixels = gray[outside_band > 0]
    if inside_pixels.size < 50 or outside_pixels.size < 50:
        return 0.0
    return float(abs(inside_pixels.mean() - outside_pixels.mean())) / 255.0


def _rectangularity(quad: np.ndarray) -> float:
    """1.0 for perfect right angles, decaying with corner distortion."""

    deviations = []
    for index in range(4):
        a = quad[(index - 1) % 4]
        b = quad[index]
        c = quad[(index + 1) % 4]
        v1 = a - b
        v2 = c - b
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm < 1e-6:
            return 0.0
        cosine = float(np.clip(np.dot(v1, v2) / norm, -1.0, 1.0))
        angle = float(np.degrees(np.arccos(cosine)))
        deviations.append(abs(90.0 - angle))
    mean_deviation = float(np.mean(deviations))
    return float(max(0.0, 1.0 - mean_deviation / 42.0))


def _aspect_score(ratio: float) -> float:
    if ratio <= 0:
        return 0.0
    if ratio < 1:
        ratio = 1.0 / ratio
    best = min(abs(ratio - ref) / 0.75 for ref in COMMON_ASPECT_RATIOS)
    score = max(0.0, 1.0 - best)
    if ratio < 1.02 or ratio > 2.6:
        score *= 0.4
    return score


def score_quad(candidate: Candidate, image: np.ndarray, sensitivity: float) -> Candidate:
    quad = candidate.quad
    height, width = image.shape[:2]
    image_area = float(width * height)

    area_ratio = perspective.quad_area(quad) / image_area
    if area_ratio < 0.02:
        area_score = 0.0
    elif area_ratio > 0.97:
        area_score = 0.15
    else:
        area_score = float(min(1.0, (area_ratio - 0.02) / 0.35))
        if area_ratio > 0.88:
            area_score *= 0.75

    convex_score = 1.0 if perspective.polygon_is_convex(quad) else 0.0
    rect_score = _rectangularity(quad)
    edge_score = min(1.0, _edge_support(image, quad) / 90.0)
    contrast_score = min(1.0, _background_contrast(image, quad) / 0.30)
    try:
        aspect_score = _aspect_score(perspective.quad_aspect_ratio(quad))
    except perspective.InvalidQuadrilateral:
        aspect_score = 0.0

    # Higher sensitivity trusts weaker edges/contrast more.
    weights = {
        "area": 0.17,
        "rect": 0.19,
        "edge": 0.23 + 0.06 * sensitivity,
        "contrast": 0.16 + 0.06 * sensitivity,
        "aspect": 0.15,
    }
    score = (
        weights["area"] * area_score
        + weights["rect"] * rect_score
        + weights["edge"] * edge_score
        + weights["contrast"] * contrast_score
        + weights["aspect"] * aspect_score
        + 0.10 * convex_score
    )
    candidate.score = float(max(0.0, min(1.0, score / 1.10)))
    candidate.metrics = {
        "area_ratio": round(area_ratio, 3),
        "rectangularity": round(rect_score, 3),
        "edge": round(edge_score, 3),
        "contrast": round(contrast_score, 3),
        "aspect": round(aspect_score, 3),
    }
    return candidate


def _dedupe(candidates: list[Candidate], iou_threshold: float = 0.85) -> list[Candidate]:
    kept: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        duplicate = False
        for other in kept:
            if _iou(candidate.quad, other.quad) > iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def _iou(quad_a: np.ndarray, quad_b: np.ndarray) -> float:
    area_a = perspective.quad_area(quad_a)
    area_b = perspective.quad_area(quad_b)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(quad_a, quad_b)
    if intersection <= 0:
        return 0.0
    union = area_a + area_b - intersection
    return float(intersection / union) if union > 0 else 0.0


def detect_candidates(image: np.ndarray, sensitivity: float = 0.5) -> list[Candidate]:
    """Return scored, de-duplicated candidates, best first."""

    if image is None or image.size == 0:
        return []
    sensitivity = float(max(0.0, min(1.0, sensitivity)))
    work, scale = _resize_for_detection(image)
    gray = _enhanced_gray(work)
    height, width = gray.shape[:2]

    raw_quads: list[tuple[np.ndarray, str]] = []

    edges = _auto_canny(gray, sigma=0.33 + 0.12 * (1.0 - sensitivity))
    raw_quads.extend((quad, "canny") for quad in _quads_from_mask(edges, sensitivity))

    block_size = 31 + 8 * int(round(sensitivity * 2))
    block_size = block_size if block_size % 2 == 1 else block_size + 1
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        7,
    )
    raw_quads.extend((quad, "adaptive") for quad in _quads_from_mask(adaptive, sensitivity))
    raw_quads.extend(
        (quad, "adaptive_inv") for quad in _quads_from_mask(cv2.bitwise_not(adaptive), sensitivity)
    )

    raw_quads.extend((quad, "lines") for quad in _quads_from_lines(edges, sensitivity))

    # Whole-frame candidate, deliberately scored low; useful when the card
    # fills the photo and no edge is visible.
    frame_margin = 0.01
    frame = np.array(
        [
            [width * frame_margin, height * frame_margin],
            [width * (1 - frame_margin), height * frame_margin],
            [width * (1 - frame_margin), height * (1 - frame_margin)],
            [width * frame_margin, height * (1 - frame_margin)],
        ],
        dtype=np.float32,
    )
    raw_quads.append((frame, "frame"))

    candidates: list[Candidate] = []
    for quad, strategy in raw_quads:
        try:
            ordered = perspective.order_points(quad / scale)
        except perspective.InvalidQuadrilateral:
            continue
        if perspective.quad_area(ordered) < 400:
            continue
        candidate = Candidate(quad=ordered, strategy=strategy)
        score_quad(candidate, image, sensitivity)
        if candidate.score > 0.02:
            candidates.append(candidate)

    return _dedupe(candidates)[:8]


def best_candidate(image: np.ndarray, sensitivity: float = 0.5) -> Candidate | None:
    candidates = detect_candidates(image, sensitivity)
    return candidates[0] if candidates else None


def default_quad(image: np.ndarray, inset: float = 0.06) -> np.ndarray:
    """A sensible starting outline when detection fails."""

    height, width = image.shape[:2]
    dx = width * inset
    dy = height * inset
    return np.array(
        [[dx, dy], [width - dx, dy], [width - dx, height - dy], [dx, height - dy]],
        dtype=np.float32,
    )
