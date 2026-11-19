"""Shared pytest fixtures: temporary storage, database and synthetic photos.

The photos are generated, not read from disk, so the suite needs no sample
images and can verify geometry against known ground truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from database.connection import Database  # noqa: E402
from database.repository import Repository  # noqa: E402


def card_image(width: int = 680, height: int = 420) -> np.ndarray:
    """A white card with a dark header, text and a grey photo box."""

    card = np.full((height, width, 3), 246, np.uint8)
    cv2.rectangle(card, (0, 0), (width, 64), (40, 70, 120), -1)
    cv2.putText(card, "KINGDOM OF SAUDI ARABIA", (18, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(card, "ID 1234567890", (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 25, 25), 2)
    cv2.rectangle(card, (30, 190), (200, 380), (190, 190, 200), -1)
    cv2.putText(card, "NAME SURNAME", (230, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    cv2.putText(card, "VALID UNTIL 2031", (230, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (30, 30, 30), 2)
    return card


def make_photo(
    canvas_size: tuple[int, int] = (760, 1080),
    corners: np.ndarray | None = None,
    background: tuple[int, int, int] = (68, 62, 58),
    card: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Place a perspective-warped card into a photo; return image and corners."""

    height, width = canvas_size
    card = card_image() if card is None else card
    if corners is None:
        corners = np.float32(
            [[width * 0.18, height * 0.16], [width * 0.86, height * 0.20],
             [width * 0.83, height * 0.82], [width * 0.16, height * 0.78]]
        )
    corners = np.asarray(corners, np.float32)
    photo = np.full((height, width, 3), background, np.uint8)
    # A little desk texture so the background is not perfectly flat.
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 5, (height, width, 1)).astype(np.int16)
    photo = np.clip(photo.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    card_h, card_w = card.shape[:2]
    dst = np.float32([[0, 0], [card_w - 1, 0], [card_w - 1, card_h - 1], [0, card_h - 1]])
    matrix = cv2.getPerspectiveTransform(dst, corners)
    warped = cv2.warpPerspective(card, matrix, (width, height), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((card_h, card_w), 255, np.uint8), matrix, (width, height))
    photo[mask > 0] = warped[mask > 0]
    return photo, corners


@pytest.fixture
def photo() -> tuple[np.ndarray, np.ndarray]:
    return make_photo()


@pytest.fixture
def temp_config(tmp_path) -> AppConfig:
    config = AppConfig(tmp_path / "settings.json")
    for key in ("project_dir", "output_dir", "temp_dir", "thumbnail_dir"):
        config.set(key, str(tmp_path / key))
    config.save()
    config.ensure_directories()
    return config


@pytest.fixture
def repository(tmp_path) -> Repository:
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)
    repository.seed_default_profiles()
    return repository
