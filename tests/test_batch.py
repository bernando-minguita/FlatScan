"""Batch processing, pairing and source-protection tests."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from app.constants import STATUS_FAILED, STATUS_SUCCESS
from core.image_loader import load_image
from services import batch_service
from services.batch_service import BatchConfig, PairGroup, export_pairs_to_pdf, pair_by_filename, process_file
from tests.conftest import make_photo


@pytest.fixture
def photo_file(tmp_path):
    image, corners = make_photo()
    path = tmp_path / "card.jpg"
    from core.image_exporter import save_raster

    save_raster(path, image, "JPEG", dpi=150, quality=95)
    return path, corners


def _config(repository, output_dir, **overrides) -> BatchConfig:
    settings = dict(
        profile=repository.default_profile(),
        output_dir=output_dir,
        sensitivity=0.5,
        fmt="JPEG",
        dpi=300,
        quality=90,
        template="{name}_{profile}",
        policy="rename",
    )
    settings.update(overrides)
    return BatchConfig(**settings)


def test_process_file_success(photo_file, repository, tmp_path) -> None:
    source, _ = photo_file
    result = process_file(source, _config(repository, tmp_path / "out"))
    assert result.status == STATUS_SUCCESS
    assert result.output_path and load_image(result.output_path).width == 1011
    assert result.image is not None
    assert result.confidence > 0.4


def test_process_file_reports_corrupt_input(repository, tmp_path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    result = process_file(broken, _config(repository, tmp_path / "out"))
    assert result.status == STATUS_FAILED
    assert result.output_path == ""


def test_batch_never_overwrites_the_source(photo_file, repository) -> None:
    source, _ = photo_file
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    # Same folder, same base name, same format and "replace" policy: the only
    # safe outcome is a renamed output.
    config = _config(repository, source.parent, template="{name}", policy="replace")
    result = process_file(source, config)
    assert result.status == STATUS_SUCCESS
    assert result.output_path
    assert result.output_path != str(source)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_batch_pdf_skip_is_not_reported_as_success(photo_file, repository, tmp_path) -> None:
    source, _ = photo_file
    out = tmp_path / "out"
    out.mkdir()
    config = _config(repository, out, fmt="PDF", template="{name}_skip", policy="skip")
    from services.export_service import build_filename

    existing_name = build_filename(
        config.template,
        name=source.stem,
        profile=config.profile.name,
        dpi=config.dpi,
        extension=".pdf",
        include_side=False,
    )
    (out / existing_name).write_bytes(b"%PDF-1.4\n%existing")
    result = process_file(source, config)
    assert result.status == STATUS_FAILED
    assert "already exists" in result.error
    assert result.output_path == ""


def test_pairing_by_filename_groups_sides(tmp_path) -> None:
    paths = [
        tmp_path / "iqama_front.jpg",
        tmp_path / "iqama_back.jpg",
        tmp_path / "passport-F.jpg",
        tmp_path / "passport-B.jpg",
        tmp_path / "unrelated.jpg",
    ]
    groups = pair_by_filename(paths)
    ids = {group.document_id for group in groups}
    assert "iqama" in ids
    assert "passport" in ids
    assert all(group.complete for group in groups)


def test_pair_export_requires_both_sides(photo_file, repository, tmp_path) -> None:
    source, _ = photo_file
    complete = PairGroup(document_id="doc", front=source, back=source)
    incomplete = PairGroup(document_id="half", front=source)
    result = export_pairs_to_pdf(
        [complete, incomplete], _config(repository, tmp_path / "out"), tmp_path / "pairs"
    )
    assert len(result["paths"]) == 1
    assert any("half" in error for error in result["errors"])


def test_pair_export_reports_failed_side(repository, tmp_path) -> None:
    good_image, _ = make_photo()
    from core.image_exporter import save_raster

    front = tmp_path / "front.jpg"
    back = tmp_path / "back.jpg"
    save_raster(front, good_image, "JPEG")
    back.write_bytes(b"broken")
    group = PairGroup(document_id="doc", front=front, back=back)
    result = export_pairs_to_pdf(
        [group], _config(repository, tmp_path / "out"), tmp_path / "pairs"
    )
    assert result["paths"] == []
    assert any("back" in error for error in result["errors"])
    assert not (tmp_path / "pairs" / "doc_iqama.pdf").exists()


def test_collect_images_deduplicates(photo_file, tmp_path) -> None:
    source, _ = photo_file
    collected = batch_service.collect_images([source, source.parent, tmp_path / "missing"])
    resolved = [str(path.resolve()).lower() for path in collected]
    assert resolved.count(str(source.resolve()).lower()) == 1
    assert all(path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp") for path in collected)


def test_matplotlib_style_synthetic_points_are_valid() -> None:
    # Guards the validator used by batch resampling of arbitrary corners.
    from core import perspective

    quad = np.float32([[10, 10], [400, 12], [395, 300], [8, 298]])
    assert perspective.is_valid_quad(quad)
