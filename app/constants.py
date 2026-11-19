"""Global constants and filesystem locations.

Paths are derived from the location of this package so that the application can
be started from any working directory and packaged as an executable without
hard-coded absolute paths.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FlatScan"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Perspective correction for ID cards and documents"
ORG_NAME = "FlatScan"

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
IMAGE_FILE_FILTER = (
    "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp);;All files (*.*)"
)
PDF_FILE_FILTER = "PDF documents (*.pdf);;All files (*.*)"

OUTPUT_FORMATS = ("PNG", "JPEG", "TIFF", "PDF")
RASTER_FORMATS = ("PNG", "JPEG", "TIFF")
DPI_CHOICES = (150, 200, 300, 600)

OVERWRITE_RENAME = "rename"
OVERWRITE_SKIP = "skip"
OVERWRITE_REPLACE = "replace"
OVERWRITE_POLICIES = (
    (OVERWRITE_RENAME, "Rename automatically"),
    (OVERWRITE_SKIP, "Skip existing files"),
    (OVERWRITE_REPLACE, "Replace after confirmation"),
)

INTERPOLATION_NAMES = ("Nearest", "Linear", "Cubic", "Lanczos")

STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_REVIEW = "needs_review"

DEFAULT_FILENAME_TEMPLATE = "{name}_{profile}"

# Common document aspect ratios used by candidate scoring (width / height).
COMMON_ASPECT_RATIOS = (1.585, 1.414, 1.42, 1.5, 1.6, 1.33)


def _resolve_base_dir() -> Path:
    """Return the writable folder that owns runtime data.

    When frozen by PyInstaller the executable directory is used if it is
    writable (portable installs), otherwise a per-user folder is used so the
    application also works from Program Files.
    """

    if getattr(sys, "frozen", False):  # pragma: no cover - packaging path
        executable_dir = Path(sys.executable).resolve().parent
        try:
            storage = executable_dir / "storage"
            storage.mkdir(parents=True, exist_ok=True)
            # A directory can exist under Program Files yet reject writes, so
            # prove writability with a real probe before choosing it.
            probe = storage / ".write-test"
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
            return executable_dir
        except OSError:
            local = os.environ.get("LOCALAPPDATA") or str(Path.home())
            fallback = Path(local) / ORG_NAME
            (fallback / "storage").mkdir(parents=True, exist_ok=True)
            return fallback
    return Path(__file__).resolve().parent.parent


def _resolve_resource_dir() -> Path:
    """Return the folder holding bundled read-only assets."""

    if getattr(sys, "frozen", False):  # pragma: no cover - packaging path
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _resolve_base_dir()
RESOURCE_ROOT = _resolve_resource_dir()
STORAGE_DIR = PROJECT_ROOT / "storage"
PROJECTS_DIR = STORAGE_DIR / "projects"
EXPORTS_DIR = STORAGE_DIR / "exports"
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"
TEMP_DIR = STORAGE_DIR / "temp"
LOGS_DIR = STORAGE_DIR / "logs"
DATABASE_PATH = STORAGE_DIR / "app.db"
SETTINGS_PATH = STORAGE_DIR / "settings.json"
PROFILES_SEED_PATH = RESOURCE_ROOT / "profiles" / "default_profiles.json"

APP_DIRS = (
    STORAGE_DIR,
    PROJECTS_DIR,
    EXPORTS_DIR,
    THUMBNAILS_DIR,
    TEMP_DIR,
    LOGS_DIR,
)
