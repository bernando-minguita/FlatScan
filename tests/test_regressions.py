"""Regression tests for the issues found in the 2026-11 codebase review."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.config import AppConfig
from core.edit_history import EditState, UndoStack
from core.image_exporter import save_raster
from core.quality_analyzer import analyze_quality
from services.batch_service import pair_by_filename
from services.export_service import ExportItem, ExportOptions, ExportService, build_filename


# --------------------------------------------------------------- undo/redo
def test_noop_push_after_undo_preserves_redo() -> None:
    """A push of an unchanged state must not destroy the redo branch."""

    stack = UndoStack(EditState(corners=[[0, 0], [1, 0], [1, 1], [0, 1]]))
    second = stack.current.clone()
    second.rotation = 90
    stack.push("Rotate", second)
    stack.undo()
    assert stack.can_redo

    # The studio commits corners on every mouse release; an unchanged commit
    # must be a no-op and keep the redo history intact.
    stack.push("No change", stack.current)
    assert stack.can_redo
    stack.redo()
    assert stack.current.rotation == 90


def test_push_new_state_after_undo_still_truncates_redo() -> None:
    stack = UndoStack(EditState(corners=[[0, 0], [1, 0], [1, 1], [0, 1]]))
    second = stack.current.clone()
    second.rotation = 90
    stack.push("Rotate", second)
    stack.undo()
    third = stack.current.clone()
    third.rotation = 180
    stack.push("Rotate again", third)
    assert not stack.can_redo
    assert stack.current.rotation == 180


# ---------------------------------------------------------------- exports
def test_failed_raster_write_leaves_previous_file_intact(tmp_path, monkeypatch) -> None:
    """A failed 'replace' write must never truncate the existing export."""

    target = tmp_path / "output.jpg"
    image = np.zeros((40, 40, 3), np.uint8)
    save_raster(target, image, "JPEG")
    original_bytes = target.read_bytes()

    import PIL.Image

    def broken_save(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(PIL.Image.Image, "save", broken_save)
    with pytest.raises(Exception):
        save_raster(target, image, "JPEG", policy="replace")
    assert target.read_bytes() == original_bytes
    # The staging file is cleaned up too.
    assert list(tmp_path.glob("*.part")) == []


def test_declined_replacement_reports_declined(tmp_path) -> None:
    service = ExportService(AppConfig(tmp_path / "settings.json"))
    image = np.zeros((20, 20, 3), np.uint8)
    target = tmp_path / "out.png"
    save_raster(target, image, "PNG")
    item = ExportItem(display_name="out", image=image)
    options = ExportOptions(
        fmt="PNG", output_dir=tmp_path, template="{name}", include_profile=False,
        include_side=False, policy="replace",
    )
    result = service.export_item(item, options, confirm_replace=lambda _path: False)
    assert result is not None and result.declined


def test_build_filename_document_id_token() -> None:
    name = build_filename(
        "{document_id}_{name}", name="front", document_id="Doc 1", extension=".jpg"
    )
    assert name == "Doc_1_front.jpg"


# ------------------------------------------------------------ dashboard/db
def test_recent_documents_excludes_failed(repository) -> None:
    from database.models import ProjectRecord

    good = ProjectRecord(id="good-1", name="Good", status="success")
    bad = ProjectRecord(id="bad-1", name="Bad", status="failed")
    repository.create_project(good)
    repository.create_project(bad)

    stats = repository.dashboard_stats()
    recent_ids = {record.id for record in stats.recent_documents}
    assert "good-1" in recent_ids
    assert "bad-1" not in recent_ids
    assert "bad-1" in {record.id for record in stats.recent_projects}


def test_list_projects_search_escapes_wildcards(repository) -> None:
    from database.models import ProjectRecord

    repository.create_project(ProjectRecord(id="pct", name="100% match", status="success"))
    repository.create_project(ProjectRecord(id="plain", name="plain", status="success"))
    assert [r.id for r in repository.list_projects(search="100%")] == ["pct"]
    # A literal % matches only the name that contains one; "plain" must not
    # appear even though the raw wildcard would have matched it.
    assert [r.id for r in repository.list_projects(search="%")] == ["pct"]
    # _ is now a literal underscore too, not a single-character wildcard.
    assert [r.id for r in repository.list_projects(search="pl_in")] == []


def test_list_projects_status_filter(repository) -> None:
    from database.models import ProjectRecord

    repository.create_project(ProjectRecord(id="ok", name="ok", status="success"))
    repository.create_project(ProjectRecord(id="no", name="no", status="failed"))
    ids = {record.id for record in repository.list_projects(status="success")}
    assert ids == {"ok"}


# ----------------------------------------------------------------- pairing
def test_pair_by_filename_reports_duplicate_sides() -> None:
    # A trailing "2" counts as a back designation, so two files ending in
    # back words map to the same document and the second must be reported.
    paths = ["doc_front.jpg", "doc_back.jpg", "doc_back_2.jpg"]
    groups = pair_by_filename(paths)
    assert len(groups) == 1
    group = groups[0]
    assert group.complete
    assert group.conflicts and "duplicate back" in group.conflicts[0]


def test_make_pairs_reports_duplicate_assignments() -> None:
    from pathlib import Path as _Path

    from services.batch_service import make_pairs

    groups = make_pairs(
        [
            (_Path("a.jpg"), "front", "d"),
            (_Path("b.jpg"), "front", "d"),
            (_Path("c.jpg"), "back", "d"),
        ]
    )
    assert len(groups) == 1
    assert groups[0].conflicts and "duplicate front" in groups[0].conflicts[0]


def test_pair_key_groups_side_only_names_in_one_folder() -> None:
    from services.batch_service import pair_key

    assert pair_key(Path("photos/F.jpg")) == pair_key(Path("photos/B.jpg"))


# ----------------------------------------------------------------- quality
def test_below_target_uses_source_size(photo) -> None:
    image, _ = photo
    small = image[::8, ::8]
    report = analyze_quality(
        small, required_px=(4000, 2500), source_size=(small.shape[1], small.shape[0])
    )
    assert any(issue.code == "below_target" for issue in report.issues)
    # Without source dimensions the check must stay silent (it is not
    # evaluable from the output alone).
    plain = analyze_quality(small, required_px=(4000, 2500))
    assert not any(issue.code == "below_target" for issue in plain.issues)


# ----------------------------------------------------------------- config
def test_config_rejects_wrong_types(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"default_dpi": {}, "detection_sensitivity": "high"}))
    config = AppConfig(path)
    assert config.get("default_dpi") == 300
    assert config.get("detection_sensitivity") == 0.5


def test_config_accepts_numeric_strings_for_numbers(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"default_dpi": "600"}))
    config = AppConfig(path)
    assert config.get("default_dpi") == 600


# --------------------------------------------------------------- edit state
def test_edit_state_from_dict_survives_corrupt_data() -> None:
    state = EditState.from_dict(
        {"corners": [[1, "x"], [2, 3], [4, 5], [6, 7]], "rotation": "abc", "enhancement": [1, 2]}
    )
    assert len(state.corners) == 4
    assert all(isinstance(value, float) for point in state.corners for value in point)
    assert state.rotation == 0
    assert isinstance(state.enhancement, dict)


def test_undo_stack_from_dict_drops_corrupt_entries() -> None:
    first = EditState(corners=[[0, 0], [1, 0], [1, 1], [0, 1]]).to_dict()
    second = dict(first, rotation=90)
    stack = UndoStack.from_dict(
        {"states": [first, "not-a-dict", second], "labels": ["a", "b", "c"], "index": 1}
    )
    assert len(stack.labels()) == 2
    assert stack.current.rotation == 90
