"""Save-project flow regression tests.

Covers the audit findings: the Save button's checked=False binding that
swallowed its own toast, missing dirty-state tracking, missing save-state
indicator, and ProjectService._write_project_file silently returning a path
after a failed write.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.context import AppContext  # noqa: E402
from core.image_loader import LoadedImage  # noqa: E402
from database.models import ProjectRecord  # noqa: E402
from services.project_service import ProjectService  # noqa: E402
from ui.correction_studio import CorrectionStudioPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def context(temp_config, repository) -> AppContext:
    return AppContext(temp_config, repository.db, repository)


# ------------------------------------------------------------- service layer
def test_write_project_file_returns_none_on_write_failure(temp_config, repository) -> None:
    """A failed portable-JSON write must not report success."""
    service = ProjectService(temp_config, repository)
    record = ProjectRecord(id="writefail", created_at="")
    # Occupy the .tmp path with a directory so write_text() raises OSError.
    (Path(str(temp_config.get("project_dir"))) / "writefail.json.tmp").mkdir()
    assert service._write_project_file(record) is None
    assert not (Path(str(temp_config.get("project_dir"))) / "writefail.json").exists()


def test_write_project_file_success_returns_path(temp_config, repository) -> None:
    service = ProjectService(temp_config, repository)
    record = ProjectRecord(id="writeok", created_at="")
    result = service._write_project_file(record)
    assert result == Path(str(temp_config.get("project_dir"))) / "writeok.json"
    assert result.exists()


# ------------------------------------------------------------------- studio
def _loaded(photo, tmp_path) -> LoadedImage:
    """A loaded image backed by a real file so projects can be re-opened."""
    image, _corners = photo
    path = tmp_path / "photo.png"
    cv2.imwrite(str(path), image)
    return LoadedImage(image=image, path=path, source_label="photo.png")


def _make_edit(page) -> None:
    """Apply a real working-state change (what a user edit produces)."""
    page.working.enhancement["brightness"] = page.working.enhancement.get("brightness", 0) + 0.1
    page._push("Brightness")


def test_save_button_click_shows_toast_and_clears_dirty(qapp, context, photo, tmp_path) -> None:
    """Regression: clicked(checked=False) used to bind to notify and mute the toast."""
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))

    assert page.save_chip.text() == "Not saved"

    _make_edit(page)
    assert page.save_chip.text() == "Unsaved changes *"

    messages: list[tuple[str, str]] = []
    page.notifyRequested.connect(lambda text, kind: messages.append((text, kind)))
    page.save_button.click()

    assert any(kind == "success" for _text, kind in messages), messages
    assert page.save_chip.text().startswith("Saved ")
    assert not page._is_dirty()
    page.deleteLater()


def test_dimension_change_marks_dirty_until_saved(qapp, context, photo, tmp_path) -> None:
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    page._save_project(notify=False)
    assert page.save_chip.text().startswith("Saved ")

    # A non-undoable dimension tweak still counts as an unsaved change.
    page.width_spin.setValue(page.width_spin.value() + 5)
    assert page.save_chip.text() == "Unsaved changes *"

    page._save_project(notify=False)
    assert page.save_chip.text().startswith("Saved ")
    page.deleteLater()


def test_undo_back_to_saved_state_clears_dirty(qapp, context, photo, tmp_path) -> None:
    """Undoing back to the saved snapshot must show Saved, not Unsaved."""
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    _make_edit(page)
    page._save_project(notify=False)
    _make_edit(page)
    assert page._is_dirty()

    page._undo()
    assert page.save_chip.text().startswith("Saved ")
    page.deleteLater()


def test_loaded_project_is_not_dirty(qapp, context, photo, tmp_path) -> None:
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    _make_edit(page)
    page._save_project(notify=False)
    record = page.project

    fresh = CorrectionStudioPage(context)
    assert fresh.load_project(record)
    assert not fresh._is_dirty()
    assert fresh.save_chip.text().startswith("Saved ")
    fresh.deleteLater()
    page.deleteLater()


def test_save_with_no_image_is_a_no_op(qapp, context) -> None:
    page = CorrectionStudioPage(context)
    page._save_project()
    assert page.project is None
    assert page.save_chip.text() == ""
    page.deleteLater()
