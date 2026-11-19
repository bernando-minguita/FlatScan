"""Application bootstrap: logging, database, theme and main window."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app import constants as app_constants
from app.config import AppConfig
from app.constants import APP_NAME, APP_VERSION, ORG_NAME
from app.context import AppContext
from database.connection import Database, DatabaseError
from database.repository import Repository
from ui.main_window import MainWindow
from ui.styles.theme import apply_theme

logger = logging.getLogger(__name__)


class FlatScanSplashScreen(QSplashScreen):
    """Custom splash screen with progress indication."""

    def __init__(self) -> None:
        # Create a pixmap for the splash
        pixmap = QPixmap(480, 320)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        # Background
        painter.fillRect(pixmap.rect(), QColor("#0F172A"))  # Dark slate
        
        # Draw logo/icon area
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2563EB"))  # Blue accent
        painter.drawRoundedRect(180, 60, 120, 120, 20, 20)
        
        # Inner rectangle for "document" look
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(195, 75, 90, 90, 10, 10)
        # Document lines
        painter.setPen(QColor("#E2E8F0"))
        painter.drawLine(210, 105, 260, 105)
        painter.drawLine(210, 125, 260, 125)
        painter.drawLine(210, 145, 240, 145)
        
        # App name
        font = QFont()
        font.setPixelSize(32)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pixmap.rect().adjusted(0, 200, 0, 0), Qt.AlignmentFlag.AlignHCenter, APP_NAME)
        
        # Version
        font.setPixelSize(14)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#94A3B8"))
        painter.drawText(pixmap.rect().adjusted(0, 240, 0, 0), Qt.AlignmentFlag.AlignHCenter, f"Version {APP_VERSION}")
        
        # Loading text
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#64748B"))
        painter.drawText(pixmap.rect().adjusted(0, 270, 0, 0), Qt.AlignmentFlag.AlignHCenter, "Loading...")
        
        painter.end()
        
        super().__init__(pixmap)
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self._progress = 0

    def show_message(self, message: str) -> None:
        """Update the loading message."""
        self.showMessage(message, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, QColor("#94A3B8"))


def configure_logging() -> Path:
    log_dir = app_constants.LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"
    handler = RotatingFileHandler(log_path, maxBytes=1_500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(logging.WARNING)
    root.addHandler(stream)
    return log_path


def _install_exception_hook(window_holder: list) -> None:
    def handle(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        )
        message = QMessageBox()
        message.setIcon(QMessageBox.Icon.Critical)
        message.setWindowTitle("Unexpected error")
        message.setText(
            "Something unexpected happened. The application is still running.\n\n"
            f"{exc_value}\n\nTechnical details were written to the log file."
        )
        message.setDetailedText("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
        message.exec()

    sys.excepthook = handle


def run() -> int:
    # Create and show splash screen immediately
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    
    splash = FlatScanSplashScreen()
    splash.show()
    app.processEvents()  # Ensure splash is displayed
    
    splash.show_message("Initializing configuration…")
    config = AppConfig()
    # Directory creation runs first so a read-only install location can
    # relocate the database, settings and log paths before anything uses them.
    config.ensure_directories()
    try:
        log_path = configure_logging()
    except OSError:  # pragma: no cover - last-resort logging to the user profile
        fallback = Path.home() / ".flatscan"
        fallback.mkdir(parents=True, exist_ok=True)
        app_constants.LOGS_DIR = fallback / "storage" / "logs"
        log_path = configure_logging()
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)

    splash.show_message("Opening database…")
    app.processEvents()
    database_path = app_constants.DATABASE_PATH
    database = Database(database_path)
    try:
        database.initialize()
    except DatabaseError as exc:
        logger.critical("Database initialisation failed: %s", exc)
        # The splash is the only visible window here; just close it instead of
        # passing an unrelated-or-missing active window to finish().
        splash.close()
        QMessageBox.critical(
            None,
            "Database error",
            f"The local database could not be opened:\n{database_path}\n\n{exc}",
        )
        return 1

    repository = Repository(database)
    splash.show_message("Loading profiles…")
    app.processEvents()
    try:
        seeded = repository.seed_default_profiles()
        if seeded:
            logger.info("Seeded %s default document profiles", seeded)
    except DatabaseError as exc:
        logger.error("Could not seed document profiles: %s", exc)

    if not config.get("default_profile_id"):
        default = repository.default_profile()
        if default is not None:
            config.set("default_profile_id", default.id)
            config.save()

    apply_theme(app, str(config.get("theme", "light")))

    splash.show_message("Building interface…")
    app.processEvents()
    context = AppContext(config, database, repository)
    window = MainWindow(context)
    _install_exception_hook([window])
    
    # Close splash and show main window (show first, then finish, so the
    # splash covers the screen until the interface is actually visible).
    window.show()
    splash.finish(window)
    logger.info("Interface ready (database: %s, log: %s)", database_path, log_path)
    return app.exec()
