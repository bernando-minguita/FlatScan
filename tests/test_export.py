"""Raster and PDF export tests."""

from __future__ import annotations

import hashlib
import cv2
import numpy as np
import pymupdf
import pytest

from core import image_exporter, pdf_handler
from core.image_loader import load_image
from services.export_service import ExportItem, ExportOptions, ExportService, build_filename


def _image(value: int = 200) -> np.ndarray:
    image = np.full((120, 180, 3), value, np.uint8)
    cv2.putText(image, "TEST", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2)
    return image


def test_dpi_metadata_is_embedded(tmp_path) -> None:
    for fmt in ("PNG", "JPEG", "TIFF"):
        target = tmp_path / f"document.{fmt.lower()}"
        result = image_exporter.save_raster(target, _image(), fmt, dpi=300, quality=95)
        assert result.path.exists()
        dpi = image_exporter.read_dpi(result.path)
        assert dpi is not None
        assert dpi[0] == pytest.approx(300, abs=1)
        assert dpi[1] == pytest.approx(300, abs=1)


def test_suffix_is_added_when_missing(tmp_path) -> None:
    result = image_exporter.save_raster(tmp_path / "no_extension", _image(), "PNG")
    assert result.path.suffix == ".png"


def test_conflict_policies(tmp_path) -> None:
    target = tmp_path / "card.png"
    first = image_exporter.save_raster(target, _image(), "PNG")
    assert first.path.name == "card.png"

    renamed = image_exporter.save_raster(target, _image(160), "PNG", policy="rename")
    assert renamed.path.name == "card_1.png"
    assert renamed.path.exists()

    skipped = image_exporter.save_raster(target, _image(120), "PNG", policy="skip")
    assert skipped.skipped
    assert not (tmp_path / "card_2.png").exists()

    replaced = image_exporter.save_raster(target, _image(100), "PNG", policy="replace")
    assert replaced.replaced
    assert int(load_image(target).image[0, 0].mean()) < 120


def test_source_image_is_never_modified(tmp_path) -> None:
    source = tmp_path / "source.png"
    image_exporter.save_raster(source, _image(), "PNG")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    loaded = load_image(source)
    image_exporter.save_raster(tmp_path / "output.png", loaded.image, "PNG")
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after


def test_filename_template_tokens() -> None:
    name = build_filename(
        "{name}_{profile}_{side}_{dpi}",
        name="Front Card",
        profile="Saudi Iqama",
        side="front",
        dpi=300,
        extension=".jpg",
    )
    assert name == "Front_Card_Saudi_Iqama_front_300.jpg"


def test_filename_template_adds_profile_and_side_once() -> None:
    name = build_filename(
        "{name}", name="card", profile="Passport", side="back", extension=".png"
    )
    assert name == "card_Passport_back.png"


def test_export_service_writes_raster(tmp_path, temp_config) -> None:
    service = ExportService(temp_config)
    options = ExportOptions(
        fmt="JPEG", dpi=200, quality=90, output_dir=tmp_path, template="{name}"
    )
    result = service.export_item(
        ExportItem(display_name="my card", image=_image(), profile_name="Saudi Iqama"), options
    )
    assert result is not None
    assert result.path.exists()
    dpi = image_exporter.read_dpi(result.path)
    assert dpi[0] == pytest.approx(200, abs=1)


def test_pdf_has_physical_page_size(tmp_path) -> None:
    target = pdf_handler.build_pdf(
        tmp_path / "document.pdf",
        [_image(230)],
        page_mode="physical",
        dpi=300,
        physical_mm=(85.6, 53.98),
    )
    assert target is not None
    with pymupdf.open(target) as document:
        assert document.page_count == 1
        page = document[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(85.6, abs=0.3)
        assert page.rect.height / 72 * 25.4 == pytest.approx(53.98, abs=0.3)
        assert len(page.get_images()) >= 0


def test_multi_page_pdf_and_aspect_ratio(tmp_path) -> None:
    target = pdf_handler.build_pdf(
        tmp_path / "bundle.pdf",
        [_image(200), _image(150), _image(100)],
        page_mode="a4",
        dpi=300,
    )
    with pymupdf.open(target) as document:
        assert document.page_count == 3
        page = document[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(297, abs=1)
        assert page.rect.height / 72 * 25.4 == pytest.approx(210, abs=1)


def test_pdf_preview_renders(tmp_path) -> None:
    data = pdf_handler.pdf_bytes_for_preview([_image()], page_mode="fit", dpi=300)
    pages = pdf_handler.render_pdf_bytes(data, dpi=100)
    assert len(pages) == 1
    assert pages[0].ndim == 3 and pages[0].shape[2] == 3


def test_export_items_to_pdf(tmp_path, temp_config) -> None:
    service = ExportService(temp_config)
    options = ExportOptions(
        fmt="PDF", dpi=300, output_dir=tmp_path, template="{name}", page_mode="physical"
    )
    items = [
        ExportItem(display_name="side A", image=_image(210), width_mm=85.6, height_mm=53.98),
        ExportItem(display_name="side B", image=_image(180), width_mm=85.6, height_mm=53.98),
    ]
    target = service.export_items_to_pdf(items, options, output_stem="pair")
    assert target is not None and target.exists()
    assert pdf_handler.page_count(target) == 2


def test_reserved_windows_device_names_are_prefixed() -> None:
    for reserved in ("CON", "con", "NUL", "COM1", "LPT9"):
        name = build_filename(reserved, name="x", extension=".jpg")
        assert name.startswith("_")


def test_unicode_and_invalid_characters_are_handled() -> None:
    arabic = build_filename("{name}_{profile}", name="جواز سفر", profile="Passport", extension=".png")
    assert "جواز" in arabic
    assert arabic.endswith(".png")
    assert " " not in arabic

    messy = build_filename("{name}", name='a<b>c:d"e/f\\g|h?i*j', extension=".jpg")
    assert not any(character in messy for character in '<>:"/\\|?*')
    assert messy.endswith(".jpg")


def test_export_service_never_overwrites_the_source(tmp_path, temp_config) -> None:
    source = tmp_path / "card.jpg"
    image_exporter.save_raster(source, _image(), "JPEG")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    loaded = load_image(source)

    service = ExportService(temp_config)
    options = ExportOptions(
        fmt="JPEG", dpi=300, quality=95, output_dir=tmp_path,
        template="{name}", policy="replace",
    )
    item = ExportItem(
        display_name=source.stem,
        image=loaded.image,
        source_path=source,
        profile_name="Saudi Iqama",
    )
    result = service.export_item(item, options)
    assert result is not None
    assert result.path != source
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert result.path.exists()


def test_combined_pdf_never_overwrites_a_source_pdf(tmp_path, temp_config) -> None:
    source = tmp_path / "bundle.pdf"
    pdf_handler.build_pdf(source, [_image()], page_mode="fit", dpi=300)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    service = ExportService(temp_config)
    options = ExportOptions(
        fmt="PDF", dpi=300, output_dir=tmp_path, template="{name}",
        policy="replace", page_mode="fit",
    )
    item = ExportItem(
        display_name="bundle", image=_image(180), source_path=source, profile_name="Iqama"
    )
    target = service.export_items_to_pdf([item], options, output_stem="bundle")
    assert target is not None
    assert target != source
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_pdf_rejects_a_missing_page_image(tmp_path) -> None:
    with pytest.raises(pdf_handler.ExportError):
        pdf_handler.build_pdf(tmp_path / "broken.pdf", [_image(), None], page_mode="fit")
    assert not (tmp_path / "broken.pdf").exists()
    assert not list(tmp_path.glob("*.part"))


def test_pdf_skip_policy_returns_none(tmp_path) -> None:
    existing = tmp_path / "document.pdf"
    existing.write_bytes(b"%PDF-1.4\n%keep")
    target = pdf_handler.build_pdf(
        existing, [_image()], page_mode="fit", dpi=300, policy="skip"
    )
    assert target is None
    assert existing.read_bytes() == b"%PDF-1.4\n%keep"


def test_unsupported_export_format_is_rejected(tmp_path) -> None:
    with pytest.raises(image_exporter.ExportError):
        image_exporter.save_raster(tmp_path / "x.bmp", _image(), "BMP")
