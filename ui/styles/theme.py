"""Theme tokens and QSS loading.

Light is the default. Both themes share the same structural QSS file, only the
colour tokens change, so every widget stays consistent.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.constants import RESOURCE_ROOT

logger = logging.getLogger(__name__)

QSS_PATH = Path(__file__).resolve().parent / "styles.qss"
# PyInstaller may place the data file at the bundle root rather than next to
# this module; fall back to the resource root before giving up.
QSS_FALLBACKS = (QSS_PATH, RESOURCE_ROOT / "ui" / "styles" / "styles.qss")
_TOKEN_RE = re.compile(r"@\[(\w+)\]")

LIGHT = {
    "background": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "sidebar": "#FFFFFF",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "text_disabled": "#94A3B8",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_soft": "#E6EEFE",
    "hover": "#F1F5F9",
    "input": "#FFFFFF",
    "success": "#15803D",
    "success_soft": "#DCFCE7",
    "warning": "#B45309",
    "warning_soft": "#FEF3C7",
    "danger": "#B91C1C",
    "danger_soft": "#FEE2E2",
    "info_soft": "#E0F2FE",
    "shadow": "rgba(15, 23, 42, 30)",
    "tooltip": "#0F172A",
}

DARK = {
    "background": "#0B1120",
    "surface": "#111A2E",
    "surface_alt": "#0F172A",
    "sidebar": "#0F172A",
    "border": "#1E293B",
    "border_strong": "#334155",
    "text": "#E2E8F0",
    "text_muted": "#94A3B8",
    "text_disabled": "#64748B",
    "accent": "#60A5FA",
    "accent_hover": "#93C5FD",
    "accent_soft": "#1E3A8A",
    "hover": "#1E293B",
    "input": "#0B1120",
    "success": "#4ADE80",
    "success_soft": "#14351F",
    "warning": "#FBBF24",
    "warning_soft": "#3A2A08",
    "danger": "#F87171",
    "danger_soft": "#3B1212",
    "info_soft": "#0C2A43",
    "shadow": "rgba(0, 0, 0, 80)",
    "tooltip": "#E2E8F0",
}

THEMES = {"light": LIGHT, "dark": DARK}


def load_stylesheet(theme: str = "light") -> str:
    tokens = THEMES.get((theme or "light").lower(), LIGHT)
    template = ""
    for candidate in QSS_FALLBACKS:
        try:
            template = candidate.read_text(encoding="utf-8")
            break
        except OSError:
            continue
    if not template:
        logger.error("Could not read the stylesheet from %s", QSS_FALLBACKS)
        return ""
    return _TOKEN_RE.sub(lambda match: tokens.get(match.group(1), "#000000"), template)


def apply_theme(app: QApplication, theme: str = "light") -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(load_stylesheet(theme))
