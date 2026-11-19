"""Automatic document detection tests."""

from __future__ import annotations

import numpy as np

from core import corner_detection, image_detector, perspective
from tests.conftest import make_photo


def test_detects_document_near_ground_truth(photo) -> None:
    image, truth = photo
    result = image_detector.detect_document(image, sensitivity=0.5)

    assert result.success, result.message
    assert result.confidence >= 0.45
    detected = perspective.order_points(result.quad)
    expected = perspective.order_points(truth)
    assert np.allclose(detected, expected, atol=30), (detected, expected)


def test_blank_image_is_not_reported_with_confidence() -> None:
    blank = np.full((600, 800, 3), 120, np.uint8)
    result = image_detector.detect_document(blank, sensitivity=0.5)
    assert (not result.success) or result.confidence < 0.6


def test_rotated_photo_is_detected() -> None:
    image, _ = make_photo()
    rotated = np.ascontiguousarray(np.rot90(image))
    result = image_detector.detect_document(rotated, sensitivity=0.5)
    assert result.success
    assert perspective.is_valid_quad(result.quad)


def test_candidates_are_scored_and_deduplicated(photo) -> None:
    image, _ = photo
    candidates = corner_detection.detect_candidates(image, sensitivity=0.7)
    assert candidates
    scores = [candidate.score for candidate in candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= score <= 1.0 for score in scores)
    assert all("rectangularity" in candidate.metrics for candidate in candidates)


def test_suggest_corners_falls_back_to_inset_frame() -> None:
    flat = np.full((400, 600, 3), 255, np.uint8)
    quad, result = image_detector.suggest_corners(flat, sensitivity=0.3)
    assert quad.shape == (4, 2)
    assert perspective.is_valid_quad(quad)
    assert isinstance(result.success, bool)


def test_default_quad_is_inside_the_image() -> None:
    quad = corner_detection.default_quad(np.zeros((200, 300, 3), np.uint8))
    assert quad[:, 0].max() < 300 and quad[:, 1].max() < 200
    assert perspective.is_valid_quad(quad)
