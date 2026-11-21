"""Plain data models for the persisted entities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class DocumentProfile:
    id: int | None = None
    name: str = ""
    description: str = ""
    width_mm: float = 85.6
    height_mm: float = 53.98
    dpi: int = 300
    format: str = "JPEG"
    quality: int = 95
    orientation: str = "landscape"
    filename_prefix: str = ""
    active: bool = True
    builtin: bool = False
    is_default: bool = False
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> "DocumentProfile":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            width_mm=float(row["width_mm"]),
            height_mm=float(row["height_mm"]),
            dpi=int(row["dpi"]),
            format=row["format"],
            quality=int(row["quality"]),
            orientation=row["orientation"],
            filename_prefix=row["filename_prefix"],
            active=bool(row["active"]),
            builtin=bool(row["builtin"]),
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def pixel_size(self) -> tuple[int, int]:
        from core.dimension_calculator import output_pixel_size

        return output_pixel_size(self.width_mm, self.height_mm, self.dpi, 0)

    def clone(self) -> "DocumentProfile":
        import copy

        return copy.deepcopy(self)


@dataclass
class ProjectRecord:
    id: str
    name: str = ""
    source_path: str = ""
    output_path: str = ""
    thumbnail_path: str = ""
    project_file_path: str = ""  # User-chosen .json path (empty = default storage/projects/{id}.json)
    profile_id: int | None = None
    profile_name: str = ""
    corners: list = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    status: str = "saved"
    error: str = ""
    document_id: str = ""
    side: str = ""
    created_at: str = ""
    updated_at: str = ""
    undo_history: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row) -> "ProjectRecord":
        try:
            corners = json.loads(row["corners"] or "[]")
        except json.JSONDecodeError:
            corners = []
        try:
            settings = json.loads(row["settings"] or "{}")
        except json.JSONDecodeError:
            settings = {}
        undo_history = settings.pop("_undo", {}) if isinstance(settings, dict) else {}
        return cls(
            id=row["id"],
            name=row["name"],
            source_path=row["source_path"] or "",
            output_path=row["output_path"] or "",
            thumbnail_path=row["thumbnail_path"] or "",
            project_file_path=row["project_file_path"] or "",
            profile_id=row["profile_id"],
            profile_name=row["profile_name"] or "",
            corners=corners,
            settings=settings,
            status=row["status"] or "",
            error=row["error"] or "",
            document_id=row["document_id"] or "",
            side=row["side"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            undo_history=undo_history,
        )

    def settings_for_storage(self) -> dict:
        data = dict(self.settings)
        if self.undo_history:
            data["_undo"] = self.undo_history
        return data

    @property
    def source_exists(self) -> bool:
        from pathlib import Path

        return bool(self.source_path) and Path(self.source_path).exists()


@dataclass
class BatchItemRecord:
    id: int | None = None
    job_id: str = ""
    source_path: str = ""
    output_path: str = ""
    status: str = "pending"
    confidence: float = 0.0
    error: str = ""
    document_id: str = ""
    side: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> "BatchItemRecord":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            source_path=row["source_path"],
            output_path=row["output_path"] or "",
            status=row["status"],
            confidence=float(row["confidence"] or 0),
            error=row["error"] or "",
            document_id=row["document_id"] or "",
            side=row["side"] or "",
            updated_at=row["updated_at"],
        )


@dataclass
class BatchJobRecord:
    id: str = ""
    name: str = ""
    profile_name: str = ""
    output_dir: str = ""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    status: str = "running"
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def from_row(cls, row) -> "BatchJobRecord":
        return cls(
            id=row["id"],
            name=row["name"],
            profile_name=row["profile_name"],
            output_dir=row["output_dir"],
            total=int(row["total"]),
            succeeded=int(row["succeeded"]),
            failed=int(row["failed"]),
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"] or "",
        )


@dataclass
class DashboardStats:
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    batches_completed: int = 0
    recent_projects: list[ProjectRecord] = field(default_factory=list)
    recent_documents: list[ProjectRecord] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if not self.total_processed:
            return 0.0
        return self.successful / self.total_processed


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
