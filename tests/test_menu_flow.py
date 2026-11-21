"""Menu bar, project open/save-as/close and studio state regression tests.

Covers the audit findings: the File menu rendered its actions *after* two
separators (so it opened with blank rows), the recent-files submenu was
rendered before the list was loaded (so it was always empty on launch), saved
project measurements were silently replaced by the profile on save, and there
was no Save As / Close / Revert path at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

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


def _shutdown(window) -> None:
    for shutdown in (window.studio.shutdown, window.batch.shutdown, window.export_center.shutdown):
        try:
            shutdown()
        except Exception:  # noqa: BLE001 - teardown must not mask failures
            pass


class _YesBox:
    """Stand-in for QMessageBox that answers "Yes" without a modal dialog.

    PySide6 static methods cannot be monkeypatched on the class itself, so the
    module-level name is patched instead.
    """

    class StandardButton:
        Yes = 1
        No = 2
        Cancel = 3
        Save = 4
        Discard = 5

    @staticmethod
    def question(*_args, **_kwargs):
        return _YesBox.StandardButton.Yes

    @staticmethod
    def warning(*_args, **_kwargs):
        return None

    @staticmethod
    def information(*_args, **_kwargs):
        return None

    @staticmethod
    def critical(*_args, **_kwargs):
        return None


@pytest.fixture
def window(qapp, context):
    """A real MainWindow, shut down cleanly so no worker thread leaks."""

    from ui.main_window import MainWindow

    main = MainWindow(context)
    yield main
    _shutdown(main)
    main.deleteLater()


def _loaded(photo, tmp_path) -> LoadedImage:
    image, _corners = photo
    path = tmp_path / "photo.png"
    cv2.imwrite(str(path), image)
    return LoadedImage(image=image, path=path, source_label="photo.png")


# ------------------------------------------------------------- service layer
def test_build_record_honours_explicit_measurements(temp_config, repository) -> None:
    """Studio overrides must be stored instead of the profile measurements."""

    from core.edit_history import EditState

    service = ProjectService(temp_config, repository)
    profile = repository.list_profiles()[0]
    state = EditState(corners=[[0, 0], [10, 0], [10, 10], [0, 10]])
    record = service.build_record(
        record=None,
        state=state,
        profile=profile,
        source_path="photo.png",
        preview_image=None,
        dpi=600,
        width_mm=123.0,
        height_mm=45.0,
    )
    assert record.settings["dpi"] == 600
    assert record.settings["width_mm"] == pytest.approx(123.0)
    assert record.settings["height_mm"] == pytest.approx(45.0)


def test_build_record_falls_back_to_profile_measurements(temp_config, repository) -> None:
    from core.edit_history import EditState

    service = ProjectService(temp_config, repository)
    profile = repository.list_profiles()[0]
    state = EditState(corners=[[0, 0], [10, 0], [10, 10], [0, 10]])
    record = service.build_record(
        record=None,
        state=state,
        profile=profile,
        source_path="photo.png",
        preview_image=None,
    )
    assert record.settings["dpi"] == profile.dpi
    assert record.settings["width_mm"] == pytest.approx(profile.width_mm)


def test_save_as_writes_a_copy_without_moving_the_project(
    temp_config, repository, tmp_path
) -> None:
    service = ProjectService(temp_config, repository)
    record = ProjectRecord(id="copy-src", name="Original", created_at="")
    record.settings = {"dpi": 300}
    target = tmp_path / "exported" / "copy"  # no suffix on purpose

    written = service.save_as(record, target)

    assert written == tmp_path / "exported" / "copy.json"
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["id"] == "copy-src"
    assert data["settings"] == {"dpi": 300}
    # The history file for the project itself is untouched.
    assert not service.project_file("copy-src").exists()


def test_open_project_file_rejects_non_object_json(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        service.open_project_file(path)


def test_open_project_file_rejects_invalid_json(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        service.open_project_file(path)


def test_open_project_file_rejects_missing_file(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    with pytest.raises(FileNotFoundError):
        service.open_project_file(tmp_path / "nope.json")


def test_open_project_file_tolerates_junk_fields(temp_config, repository, tmp_path) -> None:
    """A hand-edited file must load with sane defaults instead of raising."""

    service = ProjectService(temp_config, repository)
    path = tmp_path / "junk.json"
    path.write_text(
        json.dumps(
            {
                "id": "junk-1",
                "name": "Junk",
                "settings": "not-a-dict",
                "corners": "nope",
                "undo": [1, 2],
                "profile_id": "abc",
            }
        ),
        encoding="utf-8",
    )
    record = service.open_project_file(path)
    assert record.settings == {}
    assert record.corners == []
    assert record.undo_history == {}
    assert record.profile_id is None


# ------------------------------------------------------------- menu structure
def test_file_menu_starts_with_real_actions(window) -> None:
    """Regression: the File menu used to open with two blank separator rows."""

    file_menu = window.menuBar().actions()[0].menu()
    entries = file_menu.actions()
    assert entries, "the File menu is empty"
    assert not entries[0].isSeparator(), "the File menu starts with a separator"
    labels = [action.text() for action in entries if not action.isSeparator()]
    assert labels[0].replace("&", "") == "New correction…"
    assert any("Save project" in label for label in labels)
    assert any("Close project" in label for label in labels)


def test_standard_menus_exist(window) -> None:
    titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert titles == ["File", "Edit", "View", "Tools", "Help"]


def test_recent_files_menu_is_populated_at_startup(qapp, context, tmp_path) -> None:
    """Regression: the submenu was built before the list was loaded."""

    from ui.main_window import MainWindow

    image = tmp_path / "recent.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    context.config.set("recent_files", [str(image)])
    context.config.save()

    main = MainWindow(context)
    try:
        assert main._recent_files == [str(image)]
        labels = [action.text() for action in main._recent_files_menu.actions()]
        assert any("recent.png" in label for label in labels)
    finally:
        _shutdown(main)
        main.deleteLater()


def test_menu_actions_are_disabled_without_a_document(window) -> None:
    window.navigate("studio")
    actions = window._menu_actions
    for key in ("save", "save_as", "export", "close", "revert", "undo", "redo", "detect"):
        assert not actions[key].isEnabled(), f"{key} should be disabled with no document"


def test_menu_actions_enable_once_a_document_is_open(window, photo, tmp_path) -> None:
    window.navigate("studio")
    window.studio._begin_new_document(_loaded(photo, tmp_path))
    # A real edit is required: _push() dedupes an unchanged state.
    window.studio.working.enhancement["brightness"] = 12.0
    window.studio._push("Brightness")
    window._update_menu_state()

    actions = window._menu_actions
    assert actions["save_as"].isEnabled()
    assert actions["export"].isEnabled()
    assert actions["close"].isEnabled()
    assert actions["detect"].isEnabled()
    assert actions["save"].isEnabled()
    # Nothing saved yet, so there is nothing to revert to.
    assert not actions["revert"].isEnabled()
    assert actions["undo"].isEnabled()


def test_view_menu_disables_the_current_page(window) -> None:
    window.navigate("history")
    actions = window._menu_actions
    assert not actions["view_history"].isEnabled()
    assert actions["view_dashboard"].isEnabled()
    # Refresh only applies to data-driven pages.
    assert actions["refresh"].isEnabled()

    window.navigate("studio")
    assert not window._menu_actions["refresh"].isEnabled()


# ---------------------------------------------------------------- studio flow
def test_interpolation_change_is_undoable(qapp, context, photo, tmp_path) -> None:
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))

    page.interpolation_combo.setCurrentText("Lanczos")
    assert page.working.interpolation == "Lanczos"
    assert page.undo.can_undo

    page._undo()
    assert page.working.interpolation != "Lanczos"
    page.deleteLater()


def test_close_project_clears_the_studio(qapp, context, photo, tmp_path) -> None:
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    page._save_project(notify=False, ask_filename=False)
    assert page.loaded is not None

    with patch("ui.correction_studio.QMessageBox", _YesBox):
        page._close_project()

    assert page.loaded is None
    assert page.project is None
    assert page.undo is None
    assert page.save_chip.text() == ""
    assert page.file_chip.text() == "No image loaded"
    assert not page.save_button.isEnabled()
    page.deleteLater()


def test_loaded_project_restores_saved_measurements(qapp, context, photo, tmp_path) -> None:
    """A project saved with custom W/H/DPI must reopen with those values."""

    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    page.width_spin.setValue(101.5)
    page.height_spin.setValue(54.25)
    page.dpi_spin.setValue(600)
    page._save_project(notify=False, ask_filename=False)
    record = page.project
    assert record.settings["width_mm"] == pytest.approx(101.5)
    assert record.settings["dpi"] == 600

    fresh = CorrectionStudioPage(context)
    assert fresh.load_project(record)
    assert fresh.width_spin.value() == pytest.approx(101.5)
    assert fresh.height_spin.value() == pytest.approx(54.25)
    assert fresh.dpi_spin.value() == 600
    fresh.deleteLater()
    page.deleteLater()


def test_revert_restores_the_saved_state(qapp, context, photo, tmp_path) -> None:
    page = CorrectionStudioPage(context)
    page._begin_new_document(_loaded(photo, tmp_path))
    page._save_project(notify=False, ask_filename=False)
    saved_width = page.width_spin.value()

    page.width_spin.setValue(saved_width + 10)
    assert page._is_dirty()

    with patch("ui.correction_studio.QMessageBox", _YesBox):
        page._revert_project()

    assert page.width_spin.value() == pytest.approx(saved_width)
    assert not page._is_dirty()
    page.deleteLater()


def test_save_project_as_is_a_no_op_without_a_document(qapp, context) -> None:
    page = CorrectionStudioPage(context)
    page._save_project_as()  # must not raise or create a record
    assert page.project is None
    page.deleteLater()


def test_save_project_returns_false_when_nothing_is_loaded(qapp, context) -> None:
    page = CorrectionStudioPage(context)
    assert page._save_project() is False
    page.deleteLater()



