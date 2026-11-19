"""Shared application context passed to every window and page."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from database.connection import Database
from database.models import DocumentProfile
from database.repository import Repository
from services.batch_service import BatchService
from services.export_service import ExportService
from services.project_service import ProjectService
from .config import AppConfig


class AppContext(QObject):
    """Bundles settings, persistence and services plus cross-page signals."""

    profilesChanged = Signal()
    settingsChanged = Signal()
    historyChanged = Signal()

    def __init__(self, config: AppConfig, database: Database, repository: Repository) -> None:
        super().__init__()
        self.config = config
        self.database = database
        self.repository = repository
        self.projects = ProjectService(config, repository)
        self.exports = ExportService(config)
        self.batch = BatchService(config)

    # -------------------------------------------------------------- profiles
    def profiles(self, active_only: bool = False) -> list[DocumentProfile]:
        return self.repository.list_profiles(active_only=active_only)

    def profile_by_name(self, name: str) -> DocumentProfile | None:
        return self.repository.get_profile_by_name(name)

    def current_profile(self) -> DocumentProfile:
        profile_id = self.config.get("default_profile_id")
        profile = self.repository.get_profile(profile_id) if profile_id else None
        if profile is None:
            profile = self.repository.default_profile()
        if profile is None:
            profiles = self.repository.list_profiles()
            profile = profiles[0] if profiles else DocumentProfile(name="Custom Card")
        return profile

    def notify_profiles_changed(self) -> None:
        self.profilesChanged.emit()

    # -------------------------------------------------------------- settings
    def save_settings(self) -> None:
        self.config.save()
        self.settingsChanged.emit()

    # --------------------------------------------------------------- cleanup
    def cleanup_temp(self, max_age_days: int = 2) -> int:
        """Remove stale files and folders from the temporary directory.

        PDF imports create ``pdf_<hex>`` subfolders full of page renders; they
        must be removed as well or the temp directory grows unboundedly.
        """

        import shutil
        import time
        from pathlib import Path

        directory = Path(str(self.config.get("temp_dir")))
        if not directory.is_dir():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for entry in directory.iterdir():
            try:
                if entry == directory or entry.is_symlink():
                    continue
                if entry.stat().st_mtime >= cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
                elif entry.is_file():
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
