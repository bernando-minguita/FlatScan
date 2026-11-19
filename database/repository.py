"""Repository layer: all SQL lives here."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.constants import PROFILES_SEED_PATH
from .connection import Database, DatabaseError
from .models import (
    BatchJobRecord,
    DashboardStats,
    DocumentProfile,
    ProjectRecord,
    json_dumps,
    utc_now,
)

logger = logging.getLogger(__name__)


def _validate_profile(profile: DocumentProfile) -> None:
    """Repository-level guard so direct API use cannot store unusable sizes."""

    import math

    name = profile.name.strip()
    if not name:
        raise DatabaseError("The profile needs a name.")
    for value, label in ((profile.width_mm, "width"), (profile.height_mm, "height")):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DatabaseError(f"The profile {label} must be a number.") from exc
        if not math.isfinite(number) or number <= 0 or number > 2000:
            raise DatabaseError(f"The profile {label} must be between 0 and 2000 mm.")
    try:
        dpi = int(profile.dpi)
    except (TypeError, ValueError) as exc:
        raise DatabaseError("The profile DPI must be a number.") from exc
    if dpi < 72 or dpi > 1200:
        raise DatabaseError("The profile DPI must be between 72 and 1200.")
    if int(profile.quality) < 50 or int(profile.quality) > 100:
        raise DatabaseError("The profile quality must be between 50 and 100.")
    if profile.orientation not in ("landscape", "portrait", "square"):
        raise DatabaseError("The profile orientation must be landscape, portrait or square.")


class Repository:
    def __init__(self, database: Database) -> None:
        self.db = database

    # -------------------------------------------------------------- profiles
    def seed_default_profiles(self, seed_path: Path | str = PROFILES_SEED_PATH) -> int:
        """Insert the shipped profiles when the table is empty."""

        with self.db.connect() as connection:
            existing = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if existing:
                return 0
            defaults = self._read_seed(seed_path)
            for index, profile in enumerate(defaults):
                connection.execute(
                    """
                    INSERT INTO profiles(name, description, width_mm, height_mm, dpi, format,
                                         quality, orientation, filename_prefix, active,
                                         builtin, is_default, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        profile["name"],
                        profile.get("description", ""),
                        float(profile.get("width_mm", 85.6)),
                        float(profile.get("height_mm", 53.98)),
                        int(profile.get("dpi", 300)),
                        profile.get("format", "JPEG"),
                        int(profile.get("quality", 95)),
                        profile.get("orientation", "landscape"),
                        profile.get("filename_prefix", ""),
                        1 if profile.get("active", True) else 0,
                        1 if profile.get("builtin", True) else 0,
                        1 if index == 0 else 0,
                        utc_now(),
                        utc_now(),
                    ),
                )
            return len(defaults)

    @staticmethod
    def _read_seed(seed_path: Path | str) -> list[dict]:
        path = Path(seed_path)
        if not path.exists():
            logger.warning("Profiles seed file missing: %s", path)
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not read profiles seed: %s", exc)
            return []
        return list(data.get("profiles", []))

    def list_profiles(self, active_only: bool = False) -> list[DocumentProfile]:
        query = "SELECT * FROM profiles"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY is_default DESC, name COLLATE NOCASE"
        with self.db.connect() as connection:
            return [DocumentProfile.from_row(row) for row in connection.execute(query)]

    def get_profile(self, profile_id: int | None) -> DocumentProfile | None:
        if profile_id is None:
            return None
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE id = ?", (int(profile_id),)
            ).fetchone()
        return DocumentProfile.from_row(row) if row else None

    def get_profile_by_name(self, name: str) -> DocumentProfile | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        return DocumentProfile.from_row(row) if row else None

    def default_profile(self) -> DocumentProfile | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE is_default = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                row = connection.execute("SELECT * FROM profiles ORDER BY id LIMIT 1").fetchone()
        return DocumentProfile.from_row(row) if row else None

    def create_profile(self, profile: DocumentProfile) -> int:
        _validate_profile(profile)
        name = profile.name.strip()
        with self.db.connect() as connection:
            duplicate = connection.execute(
                "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if duplicate:
                raise DatabaseError(f"A profile named '{name}' already exists.")
            cursor = connection.execute(
                """
                INSERT INTO profiles(name, description, width_mm, height_mm, dpi, format,
                                     quality, orientation, filename_prefix, active,
                                     builtin, is_default, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?,?)
                """,
                (
                    name,
                    profile.description.strip(),
                    float(profile.width_mm),
                    float(profile.height_mm),
                    int(profile.dpi),
                    profile.format,
                    int(profile.quality),
                    profile.orientation,
                    profile.filename_prefix.strip(),
                    1 if profile.active else 0,
                    utc_now(),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def update_profile(self, profile: DocumentProfile) -> None:
        if profile.id is None:
            raise DatabaseError("Cannot update a profile without an id.")
        _validate_profile(profile)
        name = profile.name.strip()
        with self.db.connect() as connection:
            duplicate = connection.execute(
                "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE AND id != ?",
                (name, profile.id),
            ).fetchone()
            if duplicate:
                raise DatabaseError(f"A profile named '{name}' already exists.")
            connection.execute(
                """
                UPDATE profiles
                   SET name = ?, description = ?, width_mm = ?, height_mm = ?, dpi = ?,
                       format = ?, quality = ?, orientation = ?, filename_prefix = ?,
                       active = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    name,
                    profile.description.strip(),
                    float(profile.width_mm),
                    float(profile.height_mm),
                    int(profile.dpi),
                    profile.format,
                    int(profile.quality),
                    profile.orientation,
                    profile.filename_prefix.strip(),
                    1 if profile.active else 0,
                    utc_now(),
                    profile.id,
                ),
            )
            if profile.is_default:
                self._set_default(connection, profile.id)

    def delete_profile(self, profile_id: int) -> None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT builtin, is_default FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if row is None:
                raise DatabaseError("The profile no longer exists.")
            if row["builtin"]:
                raise DatabaseError("Built-in profiles cannot be deleted. You can deactivate it instead.")
            connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            if row["is_default"]:
                first = connection.execute(
                    "SELECT id FROM profiles ORDER BY id LIMIT 1"
                ).fetchone()
                if first:
                    self._set_default(connection, first["id"])

    def duplicate_profile(self, profile_id: int) -> int:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise DatabaseError("The profile no longer exists.")
        clone = profile.clone()
        clone.name = self._unique_name(f"{profile.name} copy")
        clone.builtin = False
        clone.is_default = False
        clone.id = None
        return self.create_profile(clone)

    def _unique_name(self, base: str) -> str:
        name = base
        index = 2
        while self.get_profile_by_name(name) is not None:
            name = f"{base} {index}"
            index += 1
        return name

    def set_default_profile(self, profile_id: int) -> None:
        with self.db.connect() as connection:
            exists = connection.execute(
                "SELECT id FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if not exists:
                raise DatabaseError("The profile no longer exists.")
            self._set_default(connection, profile_id)

    @staticmethod
    def _set_default(connection, profile_id: int) -> None:
        connection.execute("UPDATE profiles SET is_default = 0 WHERE is_default = 1")
        connection.execute(
            "UPDATE profiles SET is_default = 1, updated_at = ? WHERE id = ?",
            (utc_now(), profile_id),
        )

    def restore_default_profiles(self) -> int:
        """Re-create or refresh the shipped profiles, keeping custom ones."""

        defaults = self._read_seed(PROFILES_SEED_PATH)
        restored = 0
        with self.db.connect() as connection:
            for profile in defaults:
                row = connection.execute(
                    "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE", (profile["name"],)
                ).fetchone()
                if row:
                    connection.execute(
                        """
                        UPDATE profiles
                           SET description = ?, width_mm = ?, height_mm = ?, dpi = ?,
                               format = ?, quality = ?, orientation = ?, filename_prefix = ?,
                               builtin = 1, active = 1, updated_at = ?
                         WHERE id = ?
                        """,
                        (
                            profile.get("description", ""),
                            float(profile.get("width_mm", 85.6)),
                            float(profile.get("height_mm", 53.98)),
                            int(profile.get("dpi", 300)),
                            profile.get("format", "JPEG"),
                            int(profile.get("quality", 95)),
                            profile.get("orientation", "landscape"),
                            profile.get("filename_prefix", ""),
                            utc_now(),
                            row["id"],
                        ),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO profiles(name, description, width_mm, height_mm, dpi,
                                             format, quality, orientation, filename_prefix,
                                             active, builtin, is_default, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,1,1,0,?,?)
                        """,
                        (
                            profile["name"],
                            profile.get("description", ""),
                            float(profile.get("width_mm", 85.6)),
                            float(profile.get("height_mm", 53.98)),
                            int(profile.get("dpi", 300)),
                            profile.get("format", "JPEG"),
                            int(profile.get("quality", 95)),
                            profile.get("orientation", "landscape"),
                            profile.get("filename_prefix", ""),
                            utc_now(),
                            utc_now(),
                        ),
                    )
                restored += 1
            has_default = connection.execute(
                "SELECT id FROM profiles WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            if not has_default:
                first = connection.execute(
                    "SELECT id FROM profiles ORDER BY id LIMIT 1"
                ).fetchone()
                if first:
                    self._set_default(connection, first["id"])
        return restored

    # -------------------------------------------------------------- projects
    def create_project(self, record: ProjectRecord) -> str:
        if not record.id:
            record.id = str(uuid.uuid4())
        record.created_at = record.created_at or utc_now()
        record.updated_at = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects(id, name, source_path, output_path, thumbnail_path,
                                     profile_id, profile_name, corners, settings, status,
                                     error, document_id, side, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.name,
                    record.source_path,
                    record.output_path,
                    record.thumbnail_path,
                    record.profile_id,
                    record.profile_name,
                    json_dumps(record.corners),
                    json_dumps(record.settings_for_storage()),
                    record.status,
                    record.error,
                    record.document_id,
                    record.side,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record.id

    def update_project(self, record: ProjectRecord) -> None:
        record.updated_at = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE projects
                   SET name = ?, source_path = ?, output_path = ?, thumbnail_path = ?,
                       profile_id = ?, profile_name = ?, corners = ?, settings = ?,
                       status = ?, error = ?, document_id = ?, side = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    record.name,
                    record.source_path,
                    record.output_path,
                    record.thumbnail_path,
                    record.profile_id,
                    record.profile_name,
                    json_dumps(record.corners),
                    json_dumps(record.settings_for_storage()),
                    record.status,
                    record.error,
                    record.document_id,
                    record.side,
                    record.updated_at,
                    record.id,
                ),
            )

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return ProjectRecord.from_row(row) if row else None

    @staticmethod
    def _like_pattern(search: str) -> str:
        """Escape LIKE wildcards so user input is matched literally."""

        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def list_projects(
        self,
        limit: int | None = None,
        search: str = "",
        status: str | None = None,
    ) -> list[ProjectRecord]:
        clauses: list[str] = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search:
            pattern = self._like_pattern(search)
            clauses.append(
                "(name LIKE ? ESCAPE '\\' OR profile_name LIKE ? ESCAPE '\\' "
                "OR source_path LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        query = "SELECT * FROM projects"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        with self.db.connect() as connection:
            return [ProjectRecord.from_row(row) for row in connection.execute(query, params)]

    def delete_project(self, project_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def clear_history(self) -> int:
        with self.db.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            connection.execute("DELETE FROM projects")
        return int(count)

    def purge_history(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0)
        with self.db.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE created_at < ?", (cutoff.isoformat(),)
            )
            return int(cursor.rowcount or 0)

    def dashboard_stats(self) -> DashboardStats:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS bad
                  FROM projects
                """
            ).fetchone()
            batches = connection.execute(
                "SELECT COUNT(*) FROM batch_jobs WHERE status = 'completed'"
            ).fetchone()[0]
        recent_projects = self.list_projects(limit=6)
        # Only successfully processed documents belong in the recent-documents
        # panel; the previous code passed the identical unfiltered call, so
        # failed/needs-review rows leaked into it.
        recent_documents = self.list_projects(limit=6, status="success")
        return DashboardStats(
            total_processed=int(row["total"] or 0),
            successful=int(row["ok"] or 0),
            failed=int(row["bad"] or 0),
            batches_completed=int(batches or 0),
            recent_projects=recent_projects,
            recent_documents=recent_documents,
        )

    # ------------------------------------------------------------ batch jobs
    def create_batch_job(self, record: BatchJobRecord) -> str:
        if not record.id:
            record.id = str(uuid.uuid4())
        record.started_at = record.started_at or utc_now()
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_jobs(id, name, profile_name, output_dir, total,
                                       succeeded, failed, status, started_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.name,
                    record.profile_name,
                    record.output_dir,
                    record.total,
                    record.succeeded,
                    record.failed,
                    record.status,
                    record.started_at,
                ),
            )
        return record.id

    def update_batch_job(
        self,
        job_id: str,
        *,
        succeeded: int | None = None,
        failed: int | None = None,
        status: str | None = None,
        finish: bool = False,
    ) -> None:
        updates = []
        params: list = []
        if succeeded is not None:
            updates.append("succeeded = ?")
            params.append(int(succeeded))
        if failed is not None:
            updates.append("failed = ?")
            params.append(int(failed))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if finish:
            updates.append("finished_at = ?")
            params.append(utc_now())
        if not updates:
            return
        params.append(job_id)
        with self.db.connect() as connection:
            connection.execute(
                f"UPDATE batch_jobs SET {', '.join(updates)} WHERE id = ?", params
            )

    def list_batch_jobs(self, limit: int = 20) -> list[BatchJobRecord]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_jobs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            return [BatchJobRecord.from_row(row) for row in rows]

    def add_batch_item(
        self,
        job_id: str,
        source_path: str,
        status: str = "pending",
        output_path: str = "",
        confidence: float = 0.0,
        error: str = "",
        document_id: str = "",
        side: str = "",
    ) -> None:
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_items(job_id, source_path, output_path, status,
                                        confidence, error, document_id, side, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    source_path,
                    output_path,
                    status,
                    float(confidence),
                    error,
                    document_id,
                    side,
                    utc_now(),
                ),
            )

    def batch_items(self, job_id: str) -> list:
        from .models import BatchItemRecord

        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM batch_items WHERE job_id = ? ORDER BY id", (job_id,)
            )
            return [BatchItemRecord.from_row(row) for row in rows]
