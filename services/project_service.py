"""Project persistence: SQLite history plus portable JSON project files."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.config import AppConfig
from database.models import DocumentProfile, ProjectRecord
from database.repository import Repository
from core.edit_history import EditState, UndoStack
from core.image_loader import image_info, is_supported, save_thumbnail

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, config: AppConfig, repository: Repository) -> None:
        self.config = config
        self.repository = repository

    # --------------------------------------------------------------- helpers
    def projects_dir(self) -> Path:
        path = Path(str(self.config.get("project_dir")))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def project_file(self, project_id: str) -> Path:
        return self.projects_dir() / f"{project_id}.json"

    def _thumbnail_path(self, project_id: str) -> Path:
        directory = Path(str(self.config.get("thumbnail_dir")))
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{project_id}.jpg"

    def _write_thumbnail(self, project_id: str, image: np.ndarray) -> str:
        try:
            path = save_thumbnail(image, self._thumbnail_path(project_id), 360)
            return str(path)
        except (OSError, ValueError) as exc:
            logger.warning("Thumbnail could not be written: %s", exc)
            return ""

    def _write_project_file(self, record: ProjectRecord) -> Path | None:
        """Write the portable JSON sidecar; None means the write failed.

        Uses ``record.project_file_path`` when the user has chosen a custom
        location; otherwise falls back to ``storage/projects/{id}.json``.
        """
        if record.project_file_path:
            path = Path(record.project_file_path)
        else:
            path = self.project_file(record.id)
        return self._write_payload(path, self.project_payload(record))

    @staticmethod
    def project_payload(record: ProjectRecord) -> dict:
        """The portable, human-readable representation of a project record."""

        return {
            "format_version": 1,
            "id": record.id,
            "name": record.name,
            "source_path": record.source_path,
            "output_path": record.output_path,
            "thumbnail_path": record.thumbnail_path,
            "profile_name": record.profile_name,
            "profile_id": record.profile_id,
            "corners": record.corners,
            "settings": record.settings,
            "status": record.status,
            "document_id": record.document_id,
            "side": record.side,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "undo": record.undo_history,
        }

    @staticmethod
    def _write_payload(path: Path, data: dict) -> Path | None:
        """Atomically write ``data`` as JSON; None means the write failed."""

        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            # Atomic replace keeps the history JSON readable if the app is
            # interrupted mid-save; a half-written file never becomes current.
            temporary.replace(path)
        except (OSError, TypeError, ValueError) as exc:
            logger.error("Project file could not be written: %s", exc)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return path

    # ----------------------------------------------------------------- save
    def build_record(
        self,
        *,
        record: ProjectRecord | None,
        state: EditState,
        profile: DocumentProfile | None,
        source_path: str,
        preview_image: np.ndarray | None,
        project_name: str = "",
        document_id: str = "",
        side: str = "",
        status: str = "success",
        output_path: str = "",
        error: str = "",
        undo: UndoStack | None = None,
        source_image: np.ndarray | None = None,
        dpi: int | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
        project_file_path: str = "",
    ) -> ProjectRecord:
        is_new = record is None or not record.id
        if is_new:
            record = ProjectRecord(id=str(uuid.uuid4()), created_at="")
        assert record is not None
        if project_file_path:
            record.project_file_path = project_file_path
        if project_name:
            record.name = project_name
        elif not record.name:
            record.name = Path(source_path).stem or "Untitled document"
        record.source_path = source_path or record.source_path
        if output_path:
            record.output_path = output_path
        record.profile_id = profile.id if profile else record.profile_id
        record.profile_name = profile.name if profile else record.profile_name
        record.corners = [list(map(float, point)) for point in state.corners]
        # The studio lets the user override the profile measurements, so an
        # explicit value always wins; falling back to the profile keeps the
        # batch/export call sites (which pass no overrides) unchanged.
        effective_dpi = dpi if dpi is not None else (
            profile.dpi if profile else int(self.config.get("default_dpi", 300))
        )
        effective_width = width_mm if width_mm is not None else (
            profile.width_mm if profile else None
        )
        effective_height = height_mm if height_mm is not None else (
            profile.height_mm if profile else None
        )
        settings = {
            "rotation": state.rotation,
            "auto_orientation": state.auto_orientation,
            "enhancement": dict(state.enhancement),
            "interpolation": state.interpolation,
            "dpi": int(effective_dpi),
            "width_mm": effective_width,
            "height_mm": effective_height,
        }
        record.settings = settings
        if undo is not None:
            record.undo_history = undo.to_dict()
        record.status = status
        record.error = error
        if document_id:
            record.document_id = document_id
        if side:
            record.side = side

        thumbnail_source = preview_image if preview_image is not None else source_image
        if thumbnail_source is not None:
            written = self._write_thumbnail(record.id, thumbnail_source)
            # A failed write must not clear the previously stored thumbnail
            # path: the old file still exists and is still valid.
            if written:
                record.thumbnail_path = written

        if is_new:
            self.repository.create_project(record)
        else:
            self.repository.update_project(record)
        self._write_project_file(record)
        return record

    def mark_exported(self, record: ProjectRecord) -> None:
        self.repository.update_project(record)
        self._write_project_file(record)

    def set_status(self, record: ProjectRecord, status: str, error: str = "") -> None:
        record.status = status
        record.error = error
        self.repository.update_project(record)
        # Keep the portable project file in step with the database row.
        self._write_project_file(record)

    # ---------------------------------------------------------------- open
    def load(self, project_id: str) -> ProjectRecord | None:
        return self.repository.get_project(project_id)

    def open_project_file(self, path: Path | str) -> ProjectRecord:
        """Read a project JSON file and register it in the database."""

        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"The project file does not exist:\n{file_path}")
        if not file_path.is_file():
            raise ValueError("The selected path is not a file.")
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"This is not a valid FlatScan project file (invalid JSON):\n{exc}"
            ) from exc
        except OSError as exc:
            raise OSError(f"The project file could not be read:\n{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(
                "This is not a FlatScan project file: the top-level JSON value "
                "must be an object."
            )
        corners = data.get("corners")
        if not isinstance(corners, list) or len(corners) != 4:
            corners = []  # corrupt portable file: register with empty corners
        settings = data.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        undo = data.get("undo")
        if not isinstance(undo, dict):
            undo = {}
        profile_id = data.get("profile_id")
        try:
            profile_id = int(profile_id) if profile_id is not None else None
        except (TypeError, ValueError):
            profile_id = None
        record = ProjectRecord(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or file_path.stem),
            source_path=str(data.get("source_path") or ""),
            output_path=str(data.get("output_path") or ""),
            thumbnail_path=str(data.get("thumbnail_path") or ""),
            profile_id=profile_id,
            profile_name=str(data.get("profile_name") or ""),
            corners=corners,
            settings=settings,
            status=str(data.get("status") or "saved"),
            document_id=str(data.get("document_id") or ""),
            side=str(data.get("side") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            undo_history=undo,
        )
        existing = self.repository.get_project(record.id)
        if existing is None:
            self.repository.create_project(record)
        else:
            self.repository.update_project(record)
        return record

    def save_as(self, record: ProjectRecord, target: Path | str) -> Path:
        """Write a copy of ``record`` to an arbitrary ``.json`` path.

        The history row is untouched: "Save a copy" must not silently move the
        project that the studio is currently editing. Raises ``OSError`` when
        the file cannot be written so the caller can report it.
        """

        path = Path(target)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        written = self._write_payload(path, self.project_payload(record))
        if written is None:
            raise OSError(f"The project copy could not be written:\n{path}")
        return written


    def rebuild_state(self, record: ProjectRecord, fallback_size: tuple[int, int]) -> EditState:
        data = dict(record.settings or {})
        data.setdefault("corners", record.corners)
        return EditState.from_dict(data, fallback_size=fallback_size)

    @staticmethod
    def restore_undo(record: ProjectRecord, state: EditState) -> UndoStack:
        history = record.undo_history or {}
        if history.get("states"):
            try:
                return UndoStack.from_dict(history)
            except (ValueError, KeyError, TypeError):
                pass
        return UndoStack(state)

    def identify_missing_source(self, record: ProjectRecord) -> str | None:
        if not record.source_path:
            return "This project was saved without a source image reference."
        if not Path(record.source_path).exists():
            return (
                f"The original image is no longer at:\n{record.source_path}\n\n"
                "Use 'Relink source' to point the project to the moved file."
            )
        return None

    def relink_source(self, record: ProjectRecord, new_path: Path | str) -> ProjectRecord:
        path = Path(new_path)
        if not path.exists():
            raise FileNotFoundError(f"The selected file does not exist:\n{path}")
        if not is_supported(path):
            raise ValueError(
                f"Unsupported image format '{path.suffix}'. Choose a JPEG, PNG, BMP, "
                "TIFF or WebP image."
            )
        # Decode the header to prove the file is a readable image before the
        # history record starts pointing at it.
        image_info(path)
        record.source_path = str(path)
        if not record.name or record.name.startswith("Untitled"):
            record.name = path.stem
        self.repository.update_project(record)
        self._write_project_file(record)
        return record

    def clear_history(self) -> int:
        """Delete every project record together with its JSON file and thumbnail."""

        records = self.repository.list_projects()
        for record in records:
            self.delete(record.id, remove_project_file=True)
        return len(records)

    def purge_old(self, days: int) -> int:
        """Delete records older than ``days`` days, including their files."""

        if days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        for record in self.repository.list_projects():
            stamp = record.created_at or record.updated_at
            if not stamp:
                continue
            try:
                created = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                self.delete(record.id, remove_project_file=True)
                removed += 1
        return removed

    def delete(self, project_id: str, remove_project_file: bool = True) -> None:
        record = self.repository.get_project(project_id)
        self.repository.delete_project(project_id)
        if remove_project_file:
            try:
                self.project_file(project_id).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not delete project file: %s", exc)
        if record and record.thumbnail_path:
            try:
                Path(record.thumbnail_path).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def state_for_record(record: ProjectRecord) -> dict:
        return dict(record.settings or {})
