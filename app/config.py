"""JSON-backed application settings with persistent defaults."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .constants import (
    APP_DIRS,
    DEFAULT_FILENAME_TEMPLATE,
    EXPORTS_DIR,
    OVERWRITE_RENAME,
    PROJECTS_DIR,
    SETTINGS_PATH,
    STORAGE_DIR,
    TEMP_DIR,
)

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "theme": "light",
    "default_profile_id": None,
    "default_dpi": 300,
    "default_format": "JPEG",
    "jpeg_quality": 95,
    "detection_sensitivity": 0.5,
    "auto_enhance": False,
    "interpolation": "Cubic",
    "project_dir": str(PROJECTS_DIR),
    "output_dir": str(EXPORTS_DIR),
    "temp_dir": str(TEMP_DIR),
    "thumbnail_dir": str(STORAGE_DIR / "thumbnails"),
    "history_retention_days": 0,
    "cleanup_temp_on_exit": True,
    "batch_continue_on_error": True,
    "batch_auto_detect": True,
    "confirm_overwrite": True,
    "confirm_delete": True,
    "show_quality_warnings": True,
    "filename_template": DEFAULT_FILENAME_TEMPLATE,
    "overwrite_policy": OVERWRITE_RENAME,
    # Name of the profile last used to save a project (empty = none). Written
    # by the Correction Studio; read at startup to preselect the same profile.
    "recent_profile": "",
    # List of recently opened files (images and projects)
    "recent_files": [],
}


class AppConfig:
    """Small settings store (key/value) persisted to a JSON file."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else SETTINGS_PATH
        self._values: dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    @staticmethod
    def _coerce(value: Any, default: Any) -> Any:
        """Reject settings whose type does not match the declared default.

        A hand-edited or corrupted ``settings.json`` must fall back to the
        default instead of raising ``TypeError``/``ValueError`` far away from
        the source (e.g. inside a batch export).
        """

        if isinstance(default, bool):
            return value if isinstance(value, bool) else default
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if isinstance(value, bool):
                return default
            try:
                return type(default)(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, str):
            return value if isinstance(value, str) else default
        return value  # None defaults (e.g. default_profile_id) accept anything

    def load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULTS:
                        self._values[key] = self._coerce(value, DEFAULTS[key])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read settings file %s: %s", self.path, exc)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:  # pragma: no cover - disk permission problem
            logger.error("Could not save settings: %s", exc)

    # --------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        self._values[key] = value

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in DEFAULTS:
                self._values[key] = value

    def reset(self) -> None:
        self._values = dict(DEFAULTS)
        self.save()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    # ----------------------------------------------------------- directories
    def _relocate_storage(self, fallback: Path) -> None:
        """Re-point every storage location at ``fallback`` after a failure.

        The read-only-install fallback must cover the database, settings and
        log paths too, not just the four directory settings — otherwise the
        app runs half-broken with paths it cannot write to.
        """

        storage = fallback / "storage"
        from app import constants

        constants.LOGS_DIR = storage / "logs"
        constants.DATABASE_PATH = storage / "app.db"
        constants.SETTINGS_PATH = storage / "settings.json"
        values = {
            "project_dir": str(storage / "projects"),
            "output_dir": str(storage / "exports"),
            "temp_dir": str(storage / "temp"),
            "thumbnail_dir": str(storage / "thumbnails"),
        }
        for key, value in values.items():
            self.set(key, value)
        self.path = constants.SETTINGS_PATH
        self.save()

    def ensure_directories(self) -> None:
        """Create the storage tree, falling back to the user profile if needed."""

        try:
            for path in APP_DIRS:
                path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - read-only install location
            fallback = Path.home() / ".flatscan"
            logger.warning("Storage directory not writable (%s); using %s", exc, fallback)
            self._relocate_storage(fallback)

        for key in ("project_dir", "output_dir", "temp_dir", "thumbnail_dir"):
            try:
                Path(self.get(key)).mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.error("Could not create directory configured for %s", key)

    def resolve_dir(self, key: str) -> Path:
        path = Path(str(self.get(key)))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover
            logger.error("Cannot create %s: %s", path, exc)
        return path
