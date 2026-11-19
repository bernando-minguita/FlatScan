"""Database schema, project persistence, settings and undo history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.config import AppConfig, DEFAULTS
from core.edit_history import EditState, UndoStack
from database.models import BatchJobRecord, ProjectRecord
from services.project_service import ProjectService


def test_schema_is_created(repository) -> None:
    with repository.db.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"profiles", "projects", "batch_jobs", "batch_items", "schema_migrations"} <= tables


def test_project_lifecycle(repository) -> None:
    record = ProjectRecord(
        id="project-1",
        name="Iqama front",
        source_path="C:/photos/iqama.jpg",
        profile_name="Saudi Iqama",
        corners=[[1, 2], [3, 4], [5, 6], [7, 8]],
        settings={"rotation": 90, "dpi": 300},
        status="success",
    )
    repository.create_project(record)
    loaded = repository.get_project("project-1")
    assert loaded is not None
    assert loaded.corners[0] == [1.0, 2.0]
    assert loaded.settings["rotation"] == 90

    loaded.name = "Renamed project"
    loaded.status = "failed"
    repository.update_project(loaded)
    updated = repository.get_project("project-1")
    assert updated.name == "Renamed project"
    assert updated.status == "failed"
    assert len(repository.list_projects(search="Renamed")) == 1

    repository.delete_project("project-1")
    assert repository.get_project("project-1") is None


def test_dashboard_statistics(repository) -> None:
    for index, status in enumerate(("success", "success", "failed")):
        repository.create_project(
            ProjectRecord(id=f"stats-{index}", name=f"doc {index}", status=status)
        )
    stats = repository.dashboard_stats()
    assert stats.total_processed == 3
    assert stats.successful == 2
    assert stats.failed == 1
    assert stats.success_rate == pytest.approx(2 / 3)


def test_purge_history_by_age(repository) -> None:
    repository.create_project(ProjectRecord(id="old", name="old", status="success"))
    old_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with repository.db.connect() as connection:
        connection.execute(
            "UPDATE projects SET created_at = ? WHERE id = ?", (old_date, "old")
        )
    repository.create_project(ProjectRecord(id="new", name="new", status="success"))
    removed = repository.purge_history(30)
    assert removed == 1
    assert repository.get_project("old") is None
    assert repository.get_project("new") is not None


def test_batch_job_and_items(repository) -> None:
    job_id = repository.create_batch_job(
        BatchJobRecord(name="Morning batch", profile_name="Saudi Iqama", total=3)
    )
    repository.add_batch_item(job_id, "a.jpg", status="success", output_path="a_out.jpg", confidence=0.8)
    repository.add_batch_item(job_id, "b.jpg", status="failed", error="Corrupted")
    repository.update_batch_job(job_id, succeeded=1, failed=1, status="completed", finish=True)

    jobs = repository.list_batch_jobs()
    assert jobs[0].status == "completed"
    assert jobs[0].succeeded == 1
    items = repository.batch_items(job_id)
    assert len(items) == 2
    assert items[1].error == "Corrupted"


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig(path)
    config.set("default_dpi", 600)
    config.set("theme", "dark")
    config.save()

    reloaded = AppConfig(path)
    assert reloaded.get("default_dpi") == 600
    assert reloaded.get("theme") == "dark"
    assert reloaded.get("unknown-key", "fallback") == "fallback"

    with pytest.raises(KeyError):
        reloaded.set("not-a-setting", 1)

    reloaded.reset()
    assert reloaded.get("default_dpi") == DEFAULTS["default_dpi"]


def test_project_service_round_trip(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    state = EditState(
        corners=[[10, 10], [900, 12], [890, 590], [8, 588]],
        rotation=90,
        auto_orientation=False,
        enhancement={"contrast": 20, "gamma": 1.1},
    )
    preview = np.full((638, 1011, 3), 210, np.uint8)
    profile = repository.default_profile()
    record = service.build_record(
        record=None,
        state=state,
        profile=profile,
        source_path=str(tmp_path / "source.jpg"),
        preview_image=preview,
        project_name="Saved document",
        undo=UndoStack(state),
    )
    assert repository.get_project(record.id) is not None
    assert Path(record.thumbnail_path).exists()
    project_file = service.project_file(record.id)
    assert project_file.exists()

    data = json.loads(project_file.read_text(encoding="utf-8"))
    assert data["corners"][0] == [10.0, 10.0]
    assert data["settings"]["rotation"] == 90

    reopened = service.open_project_file(project_file)
    assert reopened.name == "Saved document"
    restored_state = service.rebuild_state(reopened, (1011, 638))
    assert restored_state.rotation == 90
    assert restored_state.corners[0] == [10.0, 10.0]


def test_missing_source_detection_and_relink(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    missing = tmp_path / "moved.jpg"
    record = ProjectRecord(id="relink-1", name="Card", source_path=str(missing), status="success")
    repository.create_project(record)

    warning = service.identify_missing_source(record)
    assert warning is not None and "Relink" in warning

    moved = tmp_path / "new_location.jpg"
    cv2.imwrite(str(moved), np.full((50, 80, 3), 200, np.uint8))
    service.relink_source(record, moved)
    assert record.source_path == str(moved)
    assert service.identify_missing_source(record) is None


def test_undo_stack_labels_equality_and_undo_redo() -> None:
    initial = EditState(corners=[[0, 0], [10, 0], [10, 10], [0, 10]])
    stack = UndoStack(initial)
    assert not stack.can_undo and not stack.can_redo

    changed = initial.clone()
    changed.enhancement["contrast"] = 25
    stack.push("Contrast", changed)
    assert stack.can_undo
    assert stack.undo_label == "Contrast"

    rotated = changed.clone()
    rotated.rotation = 180
    stack.push("Rotate 180°", rotated)
    assert stack.labels() == ["Initial", "Contrast", "Rotate 180°"]

    undone = stack.undo()
    assert undone.rotation == 0
    assert undone.enhancement["contrast"] == 25
    assert stack.redo_label == "Rotate 180°"
    assert stack.redo().rotation == 180

    # Pushing the same state twice must not create a duplicate entry.
    stack.push("No change", stack.current)
    assert len(stack.labels()) == 3

    serialised = stack.to_dict()
    restored = UndoStack.from_dict(serialised)
    assert restored.current.rotation == 180
    assert restored.can_undo


def test_purge_and_clear_remove_project_files(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    state = EditState(corners=[[1, 1], [20, 1], [20, 20], [1, 20]])
    (tmp_path / "src.jpg").write_bytes(b"placeholder")
    record = service.build_record(
        record=None,
        state=state,
        profile=repository.default_profile(),
        source_path=str(tmp_path / "src.jpg"),
        preview_image=np.full((80, 120, 3), 200, np.uint8),
        project_name="Purgable",
    )
    json_path = service.project_file(record.id)
    thumbnail = Path(record.thumbnail_path)
    assert json_path.exists() and thumbnail.exists()

    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with repository.db.connect() as connection:
        connection.execute("UPDATE projects SET created_at = ? WHERE id = ?", (old, record.id))
    assert service.purge_old(30) == 1
    assert repository.get_project(record.id) is None
    assert not json_path.exists()
    assert not thumbnail.exists()

    second = service.build_record(
        record=None,
        state=state,
        profile=repository.default_profile(),
        source_path=str(tmp_path / "src.jpg"),
        preview_image=np.full((80, 120, 3), 200, np.uint8),
        project_name="Clearable",
    )
    second_json = service.project_file(second.id)
    assert second_json.exists()
    assert service.clear_history() == 1
    assert repository.get_project(second.id) is None
    assert not second_json.exists()


def test_relink_validates_the_replacement_image(temp_config, repository, tmp_path) -> None:
    service = ProjectService(temp_config, repository)
    record = ProjectRecord(id="relink-check", name="Card", source_path=str(tmp_path / "gone.jpg"), status="success")
    repository.create_project(record)

    text = tmp_path / "notes.txt"
    text.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError):
        service.relink_source(record, text)

    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not really a jpeg")
    with pytest.raises(Exception):
        service.relink_source(record, broken)

    good = tmp_path / "good.png"
    cv2.imwrite(str(good), np.full((40, 60, 3), 180, np.uint8))
    service.relink_source(record, good)
    stored = repository.get_project("relink-check")
    assert stored.source_path == str(good)
    data = json.loads(service.project_file(record.id).read_text(encoding="utf-8"))
    assert data["source_path"] == str(good)
    assert service.identify_missing_source(record) is None


def test_database_integrity(repository) -> None:
    assert repository.db.integrity_check()
