"""Settings-store regression tests.

Covers the 'Unknown setting: recent_profile' crash: every settings key written
through AppConfig across the codebase must be registered in DEFAULTS, and the
export/save flows must persist their preferences without raising.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import DEFAULTS, AppConfig  # noqa: E402
from app.context import AppContext  # noqa: E402
from ui.export_window import QuickExportDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def context(temp_config, repository) -> AppContext:
    return AppContext(temp_config, repository.db, repository)


# --------------------------------------------------------- whitelist audit
# Only AppConfig.set() raises "Unknown setting"; update() and load() silently
# ignore unregistered keys. This test statically scans every write site so a
# future unregistered key fails here instead of crashing the app at runtime.
_SET_RE = re.compile(r'config\.set\(\s*["\']([A-Za-z0-9_]+)["\']')
_UPDATE_RE = re.compile(r"config\.update\(\s*\{([^}]*)\}", re.S)
_DICT_KEY_RE = re.compile(r'["\']([A-Za-z0-9_]+)["\']\s*:')
_SCAN_DIRS = ("app", "database", "services", "ui", "workers")


def _written_keys() -> dict[str, list[str]]:
    root = Path(__file__).resolve().parent.parent
    writes: dict[str, list[str]] = {}
    for directory in _SCAN_DIRS:
        for path in (root / directory).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for match in _SET_RE.finditer(text):
                writes.setdefault(match.group(1), []).append(
                    f"{path.relative_to(root)}: config.set"
                )
            for match in _UPDATE_RE.finditer(text):
                for key in _DICT_KEY_RE.findall(match.group(1)):
                    writes.setdefault(key, []).append(
                        f"{path.relative_to(root)}: config.update"
                    )
    return writes


def test_every_settings_write_is_registered() -> None:
    unregistered = {
        key: sites for key, sites in _written_keys().items() if key not in DEFAULTS
    }
    assert not unregistered, (
        "Settings written by source but missing from app.config.DEFAULTS "
        f"(config.set raises 'Unknown setting' for these): {unregistered}"
    )


def test_recent_profile_is_registered_with_safe_default() -> None:
    assert "recent_profile" in DEFAULTS
    assert DEFAULTS["recent_profile"] == ""


# ------------------------------------------------------------- store rules
def test_set_unknown_key_raises_and_update_ignores(temp_config) -> None:
    with pytest.raises(KeyError):
        temp_config.set("not_a_real_setting", 1)
    # update() deliberately ignores unknown keys instead of raising.
    temp_config.update({"not_a_real_setting": 1})
    assert temp_config.get("not_a_real_setting") is None


def test_recent_profile_roundtrip(temp_config) -> None:
    temp_config.set("recent_profile", "Iqama")
    temp_config.save()
    reloaded = AppConfig(temp_config.path)
    assert reloaded.get("recent_profile") == "Iqama"


# ----------------------------------------------------- export/save flows
def test_export_dialog_flow_persists_preferences_without_errors(
    qapp, context, tmp_path
) -> None:
    """Open the export dialog, run an export, persist the preferences.

    Regression for 'Unknown setting: recent_profile' raised while saving a
    project during export.
    """

    profile = context.current_profile()
    image = np.full((40, 60, 3), 210, np.uint8)
    dialog = QuickExportDialog(context, image, "card", profile)

    # Runs the export and persists output_dir/format/quality/template/policy
    # via config.set + save_settings; must not raise.
    dialog._do_export()

    exported = list(tmp_path.rglob("*.jpg")) + list(tmp_path.rglob("*.png"))
    assert exported, "the export did not produce a file"

    # The studio's save-project path persists the recent profile.
    context.config.set("recent_profile", profile.name)
    context.save_settings()

    reloaded = AppConfig(context.config.path)
    assert reloaded.get("recent_profile") == profile.name
    assert reloaded.get("default_format") == dialog._options().fmt
    assert Path(str(reloaded.get("output_dir"))) == Path(str(context.config.get("output_dir")))
    dialog.deleteLater()


def test_studio_startup_prefers_recent_profile(context, repository) -> None:
    """A new document preselects the profile recorded in recent_profile."""

    from ui.correction_studio import CorrectionStudioPage

    profiles = repository.list_profiles()
    target = profiles[0]
    context.config.set("recent_profile", target.name)

    page = CorrectionStudioPage(context)
    assert page.profile.name == target.name
    page.deleteLater()

    # A stale/unknown recent profile falls back to the default profile.
    context.config.set("recent_profile", "No Such Profile")
    page = CorrectionStudioPage(context)
    assert page.profile.name == context.current_profile().name
    page.deleteLater()
