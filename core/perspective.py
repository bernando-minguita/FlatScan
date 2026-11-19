"""Perspective geometry: corner ordering, validation and warping."""

from __future__ import annotations

import numpy as np
import cv2

from app.constants import INTERPOLATION_NAMES


class InvalidQuadrilateral(ValueError):
    """Raised when four points cannot form a usable document outline."""


INTERPOLATION_FLAGS = {
    "Nearest": cv2.INTER_NEAREST,
    "Linear": cv2.INTER_LINEAR,
    "Cubic": cv2.INTER_CUBIC,
    "Lanczos": cv2.INTER_LANCZOS4,
}

DEFAULT_INTERPOLATION = "Cubic"


def as_quad(points) -> np.ndarray:
    """Return a float32 (4, 2) array or raise ``InvalidQuadrilateral``."""

    try:
        quad = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    except (TypeError, ValueError) as exc:
        raise InvalidQuadrilateral("Corners must be four coordinate pairs.") from exc
    if quad.shape[0] != 4:
        raise InvalidQuadrilateral("Exactly four corners are required.")
    if not np.isfinite(quad).all():
        raise InvalidQuadrilateral("Corners contain invalid coordinates.")
    return quad


def order_points(points) -> np.ndarray:
    """Order corners as top-left, top-right, bottom-right, bottom-left.

    The result is always clockwise in image coordinates, which is what
    ``cv2.getPerspectiveTransform`` expects when mapping onto a rectangle.
    Only the four extreme points are used, so slightly noisy input is safe.
    """

    pts = as_quad(points)
    if len(np.unique(pts.round(3), axis=0)) < 4:
        raise InvalidQuadrilateral("Corners overlap; adjust the handles.")

    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).ravel()
    top_left = pts[int(np.argmin(sums))]
    bottom_right = pts[int(np.argmax(sums))]
    top_right = pts[int(np.argmin(diffs))]
    bottom_left = pts[int(np.argmax(diffs))]

    quad = np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)
    if len(np.unique(quad.round(3), axis=0)) < 4:
        # Degenerate configurations (e.g. diamond shapes) can map two roles to
        # the same point; fall back to angle ordering around the centroid.
        center = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        cyclic = pts[np.argsort(angles)]
        start = int(np.argmin(cyclic.sum(axis=1)))
        quad = np.roll(cyclic, -start, axis=0).astype(np.float32)
    return quad


def polygon_is_convex(points) -> bool:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    n = len(pts)
    if n < 4:
        return False
    sign = 0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) < 1e-6:
            return False
        current = 1 if cross > 0 else -1
        if sign == 0:
            sign = current
        elif current != sign:
            return False
    return True


def quad_area(points) -> float:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return float(abs(cv2.contourArea(pts)))


def side_lengths(points) -> tuple[float, float, float, float]:
    pts = as_quad(points)
    lengths = [float(np.linalg.norm(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
    return lengths[0], lengths[1], lengths[2], lengths[3]


def is_valid_quad(points, min_area: float = 400.0, min_side: float = 8.0) -> bool:
    try:
        quad = as_quad(points)
    except InvalidQuadrilateral:
        return False
    if not polygon_is_convex(quad):
        return False
    if quad_area(quad) < min_area:
        return False
    return all(length >= min_side for length in side_lengths(quad))


def clamp_quad(points, width: int, height: int) -> np.ndarray:
    quad = as_quad(points).copy()
    quad[:, 0] = np.clip(quad[:, 0], 0, max(0, width - 1))
    quad[:, 1] = np.clip(quad[:, 1], 0, max(0, height - 1))
    return quad


def quad_aspect_ratio(points) -> float:
    """Approximate width/height ratio of a quadrilateral."""

    top, right, bottom, left = side_lengths(order_points(points))
    width = (top + bottom) / 2.0
    height = (left + right) / 2.0
    if height <= 0:
        raise InvalidQuadrilateral("Quadrilateral has no height.")
    return width / height


def quad_to_list(points) -> list[list[float]]:
    return [[round(float(x), 2), round(float(y), 2)] for x, y in as_quad(points)]


def compute_transform(
    points, width_px: int, height_px: int, order: bool = True
) -> np.ndarray:
    """Return the 3x3 transform mapping the quad onto a ``width_px`` rectangle.

    ``order=False`` keeps the caller's corner sequence. Auto-orientation relies
    on this: it deliberately rolls the outline so a sideways document maps its
    long edge to the page width, and re-sorting the corners here would discard
    that roll and stretch the result.

    Validation happens here as well as in :func:`is_valid_quad` so that calling
    this function (or :func:`warp_perspective`) directly can never hand a
    degenerate outline to OpenCV: concave, crossed, collinear and near
    zero-area quads are rejected with ``InvalidQuadrilateral`` instead of
    producing a distorted warp or a raw ``cv2.error``.
    """

    if width_px < 2 or height_px < 2:
        raise InvalidQuadrilateral("The output size must be at least 2 × 2 pixels.")
    src = order_points(points) if order else as_quad(points)
    if len(np.unique(src.round(3), axis=0)) < 4:
        raise InvalidQuadrilateral("Corners overlap; adjust the handles.")
    if not polygon_is_convex(src) or quad_area(src) < 1.0:
        raise InvalidQuadrilateral("The corners must form a convex, non-zero-area outline.")
    if min(side_lengths(src)) < 2.0:
        raise InvalidQuadrilateral("Two corners are too close together to warp.")
    dst = np.array(
        [
            [0.0, 0.0],
            [width_px - 1.0, 0.0],
            [width_px - 1.0, height_px - 1.0],
            [0.0, height_px - 1.0],
        ],
        dtype=np.float32,
    )
    try:
        matrix = cv2.getPerspectiveTransform(src, dst)
    except cv2.error as exc:  # pragma: no cover - defensive: OpenCV changed behaviour
        raise InvalidQuadrilateral("Could not compute a perspective transform.") from exc
    if matrix is None or not np.isfinite(matrix).all():
        raise InvalidQuadrilateral("Could not compute a perspective transform.")
    return matrix


def warp_perspective(
    image: np.ndarray,
    points,
    width_px: int,
    height_px: int,
    interpolation: str = DEFAULT_INTERPOLATION,
    border_mode: int = cv2.BORDER_REPLICATE,
    order: bool = True,
) -> np.ndarray:
    """Warp the quadrilateral bounded by ``points`` into a straight rectangle."""

    if image is None or image.size == 0:
        raise ValueError("No image to correct.")
    if interpolation not in INTERPOLATION_FLAGS:
        interpolation = DEFAULT_INTERPOLATION
    matrix = compute_transform(points, width_px, height_px, order=order)
    try:
        return cv2.warpPerspective(
            image,
            matrix,
            (int(width_px), int(height_px)),
            flags=INTERPOLATION_FLAGS[interpolation],
            borderMode=border_mode,
        )
    except cv2.error as exc:  # pragma: no cover - defensive
        raise InvalidQuadrilateral("The perspective warp failed.") from exc


def scale_quad(points, factor: float) -> np.ndarray:
    return (as_quad(points) * float(factor)).astype(np.float32)


def interpolate_names() -> tuple[str, ...]:
    return INTERPOLATION_NAMES
