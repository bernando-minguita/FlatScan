"""Physical dimension, DPI and orientation tests."""

from __future__ import annotations

import numpy as np
import pytest

from core import dimension_calculator, orientation, pipeline
from core.pipeline import ProcessingSettings
from database.models import DocumentProfile
from tests.conftest import make_photo


def test_mm_to_pixels_uses_the_documented_formula() -> None:
    assert dimension_calculator.mm_to_pixels(25.4, 300) == 300
    assert dimension_calculator.mm_to_pixels(85.6, 300) == 1011
    assert dimension_calculator.mm_to_pixels(53.98, 300) == 638


def test_pixel_size_swaps_for_quarter_turns() -> None:
    landscape = dimension_calculator.output_pixel_size(85.6, 53.98, 300, 0)
    portrait = dimension_calculator.output_pixel_size(85.6, 53.98, 300, 90)
    assert landscape == (1011, 638)
    assert portrait == (638, 1011)
    assert dimension_calculator.output_pixel_size(85.6, 53.98, 300, 180) == landscape


def test_invalid_dimensions_are_rejected() -> None:
    with pytest.raises(dimension_calculator.DimensionError):
        dimension_calculator.validate_dimensions(0, 54, 300)
    with pytest.raises(dimension_calculator.DimensionError):
        dimension_calculator.validate_dimensions(85.6, 54, 10)
    with pytest.raises(dimension_calculator.DimensionError):
        dimension_calculator.mm_to_pixels(85.6, 0)


def test_profile_pixel_size() -> None:
    profile = DocumentProfile(name="Test", width_mm=125.0, height_mm=88.0, dpi=300)
    assert profile.pixel_size() == (1476, 1039)


def test_pipeline_output_matches_profile_and_dpi(photo) -> None:
    image, truth = photo
    settings = ProcessingSettings(width_mm=85.6, height_mm=53.98, dpi=300, auto_orientation=True)
    document = pipeline.correct_document(image, truth, settings)
    assert document.size == (1011, 638)
    assert document.image.shape[:2] == (638, 1011)
    assert document.rotation == 0


def test_manual_rotation_swaps_the_page(photo) -> None:
    image, truth = photo
    settings = ProcessingSettings(
        width_mm=85.6, height_mm=53.98, dpi=300, rotation=90, auto_orientation=False
    )
    document = pipeline.correct_document(image, truth, settings)
    assert document.size == (638, 1011)
    assert document.rotation == 90


def test_auto_orientation_when_the_card_is_sideways() -> None:
    image, truth = make_photo()
    rotated = np.ascontiguousarray(np.rot90(image))
    height, width = image.shape[:2]
    # np.rot90 rotates counter-clockwise: (x, y) -> (y, W - 1 - x).
    rotated_truth = np.array(
        [[corner[1], width - 1 - corner[0]] for corner in truth], np.float32
    )
    settings = ProcessingSettings(width_mm=85.6, height_mm=53.98, dpi=200, auto_orientation=True)
    document = pipeline.correct_document(rotated, rotated_truth, settings)
    # The page keeps the profile's landscape orientation instead of stretching.
    assert document.size[0] > document.size[1]
    assert document.rotation == 0


def test_unknown_orientation_does_not_rotate(photo) -> None:
    assert orientation.auto_rotation(400, 700, None) == 0
    assert orientation.auto_rotation(700, 400, True) == 0
    assert orientation.auto_rotation(400, 700, True) == 90


def test_sideways_card_keeps_aspect_and_is_not_stretched() -> None:
    import cv2

    from tests.conftest import card_image

    image, truth = make_photo()
    rotated = np.ascontiguousarray(np.rot90(image))
    height, width = image.shape[:2]
    # np.rot90 rotates counter-clockwise: (x, y) -> (y, W - 1 - x).
    rotated_truth = np.array(
        [[corner[1], width - 1 - corner[0]] for corner in truth], np.float32
    )
    settings = ProcessingSettings(
        width_mm=85.6, height_mm=53.98, dpi=300, auto_orientation=True
    )
    document = pipeline.correct_document(rotated, rotated_truth, settings)
    assert document.size == (1011, 638)

    original = card_image()
    reference = cv2.resize(original, (1011, 638), interpolation=cv2.INTER_AREA)
    flipped = cv2.rotate(reference, cv2.ROTATE_180)
    differences = [
        float(cv2.absdiff(document.image, candidate).mean())
        for candidate in (reference, flipped)
    ]
    # If the outline were not re-aligned, the content would be rotated 90°
    # relative to both references (a large difference).
    assert min(differences) < 20.0


def test_enhancement_never_compounds_on_previous_enhancement(photo) -> None:
    from core import enhancement

    image, truth = photo
    params = {"contrast": 35, "brightness": 8, "gamma": 1.2, "sharpness": 25}
    plain = pipeline.correct_document(
        image, truth, ProcessingSettings(auto_orientation=False)
    ).base_image
    once = enhancement.apply_enhancements(plain, params)

    settings = ProcessingSettings(auto_orientation=False, enhancement=params)
    from_source = pipeline.correct_document(image, truth, settings).image
    assert np.array_equal(once, from_source)


def test_rotation_helpers_round_trip() -> None:
    image = np.arange(16, dtype=np.uint8).reshape(4, 4)
    rotated = orientation.rotate_image(image, 90)
    restored = orientation.rotate_image(rotated, 270)
    assert np.array_equal(image, restored)
    assert orientation.effective_size(10, 20, 90) == (20, 10)


def test_enhancement_is_identity_by_default() -> None:
    from core import enhancement

    image = np.random.default_rng(3).integers(0, 255, (40, 40, 3), dtype=np.uint8)
    restored = enhancement.apply_enhancements(image, None)
    assert np.array_equal(image, restored)
    assert enhancement.is_identity({})


def test_auto_enhance_returns_bounded_parameters() -> None:
    from core import enhancement

    dark = np.full((200, 300, 3), 40, np.uint8)
    params = enhancement.auto_enhance_params(dark)
    assert 0.3 <= params["gamma"] <= 3.0
    assert params["sharpness"] >= 0
    assert enhancement.apply_enhancements(dark, params).shape == dark.shape
    assert float(enhancement.apply_enhancements(dark, params).mean()) > float(dark.mean())
