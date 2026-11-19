"""Image decoding, colour space and PDF rasterisation tests."""

from __future__ import annotations

import numpy as np
import pymupdf
import pytest
from PIL import Image

from core import pdf_handler
from core.image_loader import ImageLoadError, load_image
from ui.image_utils import bgr_to_qimage, qimage_to_bgr


def test_rgb_png_is_converted_to_bgr(tmp_path) -> None:
    path = tmp_path / "red.png"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(path)
    loaded = load_image(path)
    assert loaded.image.shape == (10, 20, 3)
    assert loaded.image.dtype == np.uint8
    # Red in BGR is (0, 0, 255): a channel swap would make this fail.
    assert loaded.image[0, 0].tolist() == [0, 0, 255]


def test_rgba_png_drops_alpha_without_channel_swap(tmp_path) -> None:
    path = tmp_path / "blue.png"
    Image.new("RGBA", (8, 8), (0, 0, 255, 128)).save(path)
    loaded = load_image(path)
    assert loaded.image.shape == (8, 8, 3)
    assert loaded.image[0, 0].tolist() == [255, 0, 0]


def test_grayscale_is_expanded_to_three_channels(tmp_path) -> None:
    path = tmp_path / "grey.png"
    Image.new("L", (12, 6), 128).save(path)
    loaded = load_image(path)
    assert loaded.image.shape == (6, 12, 3)
    assert np.allclose(loaded.image, 128)


def test_sixteen_bit_image_loads_as_eight_bit_bgr(tmp_path) -> None:
    path = tmp_path / "deep.png"
    array = np.full((9, 11), 40000, dtype=np.uint16)
    Image.fromarray(array, mode="I;16").save(path)
    loaded = load_image(path)
    assert loaded.image.shape == (9, 11, 3)
    assert loaded.image.dtype == np.uint8


def test_exif_orientation_is_applied(tmp_path) -> None:
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (100, 50), (10, 200, 10))
    exif = image.getexif()
    exif[274] = 6  # rotate 90° clockwise when displaying
    image.save(path, exif=exif)
    loaded = load_image(path)
    assert loaded.exif_rotated
    assert (loaded.width, loaded.height) == (50, 100)


def test_unsupported_and_corrupt_files_fail_cleanly(tmp_path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("not an image", encoding="utf-8")
    with pytest.raises(ImageLoadError):
        load_image(text)

    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"\xff\xd8not really a jpeg")
    with pytest.raises(ImageLoadError):
        load_image(broken)

    with pytest.raises(ImageLoadError):
        load_image(tmp_path / "missing.png")


def test_qt_round_trip_preserves_colour_order(tmp_path) -> None:
    path = tmp_path / "green.png"
    Image.new("RGB", (16, 9), (0, 255, 0)).save(path)
    loaded = load_image(path)
    restored = qimage_to_bgr(bgr_to_qimage(loaded.image))
    assert np.array_equal(restored, loaded.image)


def test_pdf_page_render_is_bgr(tmp_path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.draw_rect(pymupdf.Rect(0, 0, 200, 100), color=None, fill=(1, 0, 0))
    pdf_path = tmp_path / "red.pdf"
    document.save(pdf_path)
    document.close()

    rendered = pdf_handler.render_pages(pdf_path, [0], dpi=72)
    assert len(rendered) == 1
    pixel = rendered[0].image[rendered[0].height // 2, rendered[0].width // 2]
    assert int(pixel[2]) > 180   # red
    assert int(pixel[0]) < 80    # blue
    assert int(pixel[1]) < 80    # green


def test_pdf_password_protection_is_reported(tmp_path) -> None:
    document = pymupdf.open()
    document.new_page()
    pdf_path = tmp_path / "locked.pdf"
    document.save(
        pdf_path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="secret",
    )
    document.close()
    with pytest.raises(pdf_handler.ExportError):
        pdf_handler.page_count(pdf_path)
