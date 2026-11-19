"""Quarter-turn rotation helpers and automatic orientation logic."""

from __future__ import annotations

import cv2
import numpy as np


VALID_ROTATIONS = (0, 90, 180, 270)


def normalize_rotation(degrees: int) -> int:
    return int(degrees) % 360


def rotate_image(image: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate clockwise by a multiple of 90 degrees."""

    degrees = normalize_rotation(degrees)
    if degrees not in VALID_ROTATIONS:
        raise ValueError("Rotation must be 0, 90, 180 or 270 degrees.")
    if degrees == 0:
        return image.copy()
    if degrees == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)


def orientation_label(width: int, height: int) -> str:
    if width == height:
        return "Square"
    return "Landscape" if width > height else "Portrait"


def auto_rotation(width: int, height: int, expected_landscape: bool | None) -> int:
    """Suggest a correction so the document matches its expected orientation.

    ``expected_landscape`` comes from the profile (physical width > height).
    When it is unknown, no rotation is applied: silently guessing would risk
    turning a portrait passport upside-down.
    """

    if expected_landscape is None:
        return 0
    is_landscape = width > height
    if width == height:
        return 0
    if is_landscape != expected_landscape:
        return 90
    return 0


def effective_size(width: int, height: int, rotation: int) -> tuple[int, int]:
    if normalize_rotation(rotation) % 180 == 90:
        return height, width
    return width, height
