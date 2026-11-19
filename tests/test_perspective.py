"""Geometry and warp tests."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from core import perspective


def test_corner_ordering_is_clockwise() -> None:
    points = np.array([[10, 10], [200, 12], [205, 120], [8, 118]], np.float32)
    ordered = perspective.order_points(points)
    assert np.allclose(ordered[0], [10, 10])     # top-left
    assert np.allclose(ordered[1], [200, 12])    # top-right
    assert np.allclose(ordered[2], [205, 120])   # bottom-right
    assert np.allclose(ordered[3], [8, 118])     # bottom-left


def test_corner_ordering_accepts_unordered_input() -> None:
    quad = perspective.order_points([[200, 120], [10, 10], [8, 118], [205, 12]])
    assert np.allclose(quad[0], [10, 10])
    assert np.allclose(quad[2], [200, 120])


def test_degenerate_quadrilaterals_are_rejected() -> None:
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.order_points([[10, 10], [10, 10], [50, 50], [80, 80]])

    crossed = np.array([[0, 0], [100, 100], [100, 0], [0, 100]], np.float32)
    assert not perspective.polygon_is_convex(crossed)
    assert not perspective.is_valid_quad(crossed, min_area=10)


def test_area_and_aspect_ratio() -> None:
    quad = np.float32([[0, 0], [200, 0], [200, 100], [0, 100]])
    assert perspective.quad_area(quad) == pytest.approx(20000)
    assert perspective.quad_aspect_ratio(quad) == pytest.approx(2.0)


def test_warp_matches_the_original_card(photo) -> None:
    image, truth = photo
    from tests.conftest import card_image

    original = card_image()
    height, width = original.shape[:2]
    warped = perspective.warp_perspective(image, truth, width, height)
    difference = cv2.absdiff(warped, original)
    assert float(difference.mean()) < 12.0
    # The header is dark and belongs at the top after correction.
    assert int(warped[10, 10].sum()) < 400
    assert int(warped[-10, width // 2].sum()) > 500


def test_warp_guarantees_the_requested_size(photo) -> None:
    image, truth = photo
    warped = perspective.warp_perspective(image, truth, 640, 400, interpolation="Lanczos")
    assert warped.shape == (400, 640, 3)


def test_warp_rejects_bad_output_size(photo) -> None:
    image, truth = photo
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.warp_perspective(image, truth, 0, 100)


def test_transform_matrix_is_finite(photo) -> None:
    _, truth = photo
    matrix = perspective.compute_transform(truth, 400, 250)
    assert matrix.shape == (3, 3)
    assert np.isfinite(matrix).all()


def test_warp_rejects_degenerate_outlines() -> None:
    image = np.zeros((200, 200, 3), np.uint8)

    concave = np.float32([[10, 10], [150, 10], [80, 80], [10, 150]])
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.warp_perspective(image, concave, 100, 100)

    collinear = np.float32([[10, 10], [60, 10], [120, 10], [180, 10]])
    assert not perspective.polygon_is_convex(collinear)
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.warp_perspective(image, collinear, 100, 100)

    valid = np.float32([[10, 10], [180, 10], [180, 180], [10, 180]])
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.warp_perspective(image, valid, 1, 1)

    overlapping = np.float32([[10, 10], [10, 10], [180, 180], [10, 180]])
    with pytest.raises(perspective.InvalidQuadrilateral):
        perspective.warp_perspective(image, overlapping, 100, 100)


def test_quad_serialisation_round_trip() -> None:
    quad = np.float32([[1.234, 5.678], [10, 1], [20, 30], [0, 20]])
    data = perspective.quad_to_list(quad)
    assert len(data) == 4 and all(len(point) == 2 for point in data)
    assert np.allclose(perspective.as_quad(data), quad, atol=0.01)
