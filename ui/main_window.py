"""Main window: sidebar navigation and page wiring."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import APP_NAME, APP_VERSION, STORAGE_DIR
from app.context import AppContext
from ui.batch_window import BatchPage
from ui.correction_studio import CorrectionStudioPage
from ui.dashboard import DashboardPage
from ui.export_window import ExportCenterPage
from ui.history_window import HistoryPage
from ui.icons import make_icon
from ui.profile_manager import ProfileManagerPage
from ui.settings_window import SettingsPage
from ui.styles.theme import apply_theme
from ui.widgets.notification import NotificationHost

NAV_ITEMS = (
    ("dashboard", "Dashboard", "dashboard"),
    ("studio", "Correction Studio", "studio"),
    ("batch", "Batch Processing", "batch"),
    ("profiles", "Document Profiles", "profiles"),
    ("history", "Processing History", "history"),
    ("export", "Export Center", "export"),
    ("settings", "Settings", "settings"),
)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._recent_files_menu: QMenu | None = None
        self._recent_files: list[str] = []

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = self._build_sidebar()
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.dashboard = DashboardPage(ctx)
        self.studio = CorrectionStudioPage(ctx)
        self.batch = BatchPage(ctx)
        self.profiles = ProfileManagerPage(ctx)
        self.history = HistoryPage(ctx)
        self.export_center = ExportCenterPage(ctx)
        self.settings = SettingsPage(ctx)
        self.pages = {
            "dashboard": self.dashboard,
            "studio": self.studio,
            "batch": self.batch,
            "profiles": self.profiles,
            "history": self.history,
            "export": self.export_center,
            "settings": self.settings,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.notifications = NotificationHost(root)
        self._wire_signals()
        # Recent files must be loaded *before* the menu is built: _build_menu()
        # renders the submenu immediately, so the previous order left it empty
        # until the first file was opened.
        self._load_recent_files()
        self._build_menu()
        self._build_status_bar()
        self.navigate("dashboard")

    # ------------------------------------------------------------------- UI
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(make_icon("studio", "#2563EB", 28).pixmap(28, 28))
        brand_column = QVBoxLayout()
        brand_column.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("NavBrand")
        caption = QLabel("Perspective corrector")
        caption.setObjectName("NavCaption")
        brand_column.addWidget(brand)
        brand_column.addWidget(caption)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand_column, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(18)

        section = QLabel("WORKSPACE")
        section.setObjectName("NavSection")
        layout.addWidget(section)
        layout.addSpacing(2)

        for key, label, icon_name in NAV_ITEMS:
            if key == "settings":
                continue
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIcon(make_icon(icon_name, "#64748B", 18))
            button.setIconSize(button.iconSize())
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            button.toggled.connect(lambda checked, b=button, i=icon_name: self._tint_nav(b, i, checked))
            layout.addWidget(button)
            self._nav_buttons[key] = button

        layout.addStretch(1)
        settings_button = QPushButton("Settings")
        settings_button.setObjectName("NavButton")
        settings_button.setCheckable(True)
        settings_button.setAutoExclusive(True)
        settings_button.setIcon(make_icon("settings", "#64748B", 18))
        settings_button.clicked.connect(lambda: self.navigate("settings"))
        settings_button.toggled.connect(
            lambda checked: self._tint_nav(settings_button, "settings", checked)
        )
        layout.addWidget(settings_button)
        self._nav_buttons["settings"] = settings_button

        privacy = QLabel("100% offline\nNo document ever leaves this PC")
        privacy.setObjectName("PrivacyBadge")
        privacy.setWordWrap(True)
        layout.addSpacing(10)
        layout.addWidget(privacy)
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("Tiny")
        layout.addWidget(version)
        return sidebar

    @staticmethod
    def _tint_nav(button: QPushButton, icon_name: str, checked: bool) -> None:
        button.setIcon(make_icon(icon_name, "#2563EB" if checked else "#64748B", 18))

    def _build_menu(self) -> None:
        """Build the standard menu bar.

        Every action is registered in ``self._menu_actions`` so
        :meth:`_update_menu_state` can enable only what applies to the page the
        user is currently looking at.
        """

        menu = self.menuBar()
        self._menu_actions: dict[str, QAction] = {}

        def add(menu_ref: QMenu, key: str, text: str, slot, shortcut: str = "", tip: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            if tip:
                action.setStatusTip(tip)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            menu_ref.addAction(action)
            self._menu_actions[key] = action
            return action

        # ------------------------------------------------------------------ File
        file_menu = menu.addMenu("&File")
        add(file_menu, "new", "&New correction…", self._new_correction, "Ctrl+N",
            "Open a photo and start a new correction")
        add(file_menu, "open_image", "Open &image…", self._open_image, "Ctrl+O",
            "Open an image in the Correction Studio")
        add(file_menu, "open_project", "Open &project…", self._open_project, "Ctrl+Shift+O",
            "Open a saved .json project file")
        self._recent_files_menu = file_menu.addMenu("Recent files")
        self._update_recent_files_menu()
        file_menu.addSeparator()
        add(file_menu, "save", "&Save project", self._save_project, "Ctrl+S",
            "Save the current correction to history")
        add(file_menu, "save_as", "Save project &as…", self._save_project_as, "Ctrl+Shift+S",
            "Write a copy of the project to a chosen file")
        add(file_menu, "revert", "&Revert to saved", self._revert_project, "",
            "Discard changes and reload the last saved version")
        add(file_menu, "close", "&Close project", self._close_project, "Ctrl+W",
            "Close the document open in the studio")
        file_menu.addSeparator()
        add(file_menu, "export", "&Export…", self._export_current, "Ctrl+E",
            "Export the corrected document")
        add(file_menu, "export_center", "Export &Center", lambda: self.navigate("export"), "",
            "Open the Export Center page")
        file_menu.addSeparator()
        add(file_menu, "batch", "&Batch processing", lambda: self.navigate("batch"), "",
            "Open Batch Processing")
        file_menu.addSeparator()
        add(file_menu, "exit", "E&xit", self.close, "Ctrl+Q", "Close FlatScan")

        # ------------------------------------------------------------------ Edit
        edit_menu = menu.addMenu("&Edit")
        add(edit_menu, "undo", "&Undo", self._undo, "Ctrl+Z", "Undo the last change")
        add(edit_menu, "redo", "&Redo", self._redo, "Ctrl+Y", "Redo the last undone change")
        edit_menu.addSeparator()
        add(edit_menu, "paste", "&Paste image", self._paste_image, "Ctrl+V",
            "Load an image from the clipboard")
        add(edit_menu, "detect", "&Detect document", self._detect_document, "Ctrl+D",
            "Run automatic document detection")
        edit_menu.addSeparator()
        add(edit_menu, "reset_corners", "Reset to &detected corners", self._reset_corners, "",
            "Restore the last automatic detection")
        add(edit_menu, "reset_image", "Reset to &original image", self._reset_to_original, "",
            "Discard every change and reload the source image")
        edit_menu.addSeparator()
        add(edit_menu, "rotate_left", "Rotate 90° &left", lambda: self._rotate(-90), "",
            "Rotate the corrected output counter-clockwise")
        add(edit_menu, "rotate_right", "Rotate 90° &right", lambda: self._rotate(90), "",
            "Rotate the corrected output clockwise")
        add(edit_menu, "rotate_180", "Rotate 1&80°", lambda: self._rotate(180), "",
            "Rotate the corrected output by 180°")

        # ------------------------------------------------------------------ View
        view_menu = menu.addMenu("&View")
        for key, label, icon in NAV_ITEMS:
            add(
                view_menu,
                f"view_{key}",
                label.replace("&", "&&"),
                lambda k=key: self.navigate(k),
                "",
                f"Go to {label}",
            )
        view_menu.addSeparator()
        add(view_menu, "refresh", "&Refresh page", self._refresh_current_page, "F5",
            "Reload the data shown on the current page")

        # ----------------------------------------------------------------- Tools
        tools_menu = menu.addMenu("&Tools")
        add(tools_menu, "profiles", "&Document profiles", lambda: self.navigate("profiles"), "",
            "Manage document measurements and defaults")
        add(tools_menu, "history", "Processing &history", lambda: self.navigate("history"), "",
            "Review and reopen processed documents")
        tools_menu.addSeparator()
        add(tools_menu, "settings", "&Settings…", lambda: self.navigate("settings"), "",
            "Change application preferences")
        tools_menu.addSeparator()
        add(tools_menu, "open_data", "Open &data folder", self._open_data_folder, "",
            "Show the folder holding the database, projects and exports")

        # ------------------------------------------------------------------ Help
        help_menu = menu.addMenu("&Help")
        add(help_menu, "shortcuts", "&Keyboard shortcuts", self._show_shortcuts, "F1",
            "List every keyboard shortcut")
        help_menu.addSeparator()
        add(help_menu, "about", "&About FlatScan", self._show_about, "",
            "Version and privacy information")

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        offline = QLabel("Offline · local processing only")
        offline.setObjectName("Tiny")
        bar.addWidget(offline)
        storage = QLabel(f"Data: {STORAGE_DIR}")
        storage.setObjectName("Tiny")
        storage.setToolTip(str(STORAGE_DIR))
        bar.addPermanentWidget(storage)

    # ------------------------------------------------------------- menu state
    def _update_menu_state(self) -> None:
        """Enable only the menu entries that apply to the current page."""

        actions = getattr(self, "_menu_actions", None)
        if not actions:
            return
        page = self._current_page_key()
        has_document = self.studio.loaded is not None
        can_undo = bool(self.studio.undo and self.studio.undo.can_undo)
        can_redo = bool(self.studio.undo and self.studio.undo.can_redo)
        dirty = self.studio.has_unsaved_changes()
        saved = self.studio.project is not None

        # Actions that only make sense with a document open in the studio.
        for key in ("save", "save_as", "export", "close", "revert", "detect",
                    "reset_corners", "reset_image", "rotate_left", "rotate_right",
                    "rotate_180"):
            actions[key].setEnabled(has_document)
        actions["save"].setEnabled(has_document and dirty)
        actions["revert"].setEnabled(has_document and saved and dirty)
        actions["undo"].setEnabled(has_document and can_undo)
        actions["redo"].setEnabled(has_document and can_redo)
        actions["close"].setEnabled(has_document)

        # "Refresh" only applies to pages that load data from the database.
        actions["refresh"].setEnabled(page in ("dashboard", "history", "profiles"))
        # Navigating to the page you are already on is pointless.
        for key, _label, _icon in NAV_ITEMS:
            actions[f"view_{key}"].setEnabled(page != key)
        actions["open_data"].setEnabled(True)

    def _current_page_key(self) -> str:
        current = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is current:
                return key
        return ""

    def _refresh_current_page(self) -> None:
        """Reload the data shown by the page the user is looking at."""

        page = self._current_page_key()
        if page == "dashboard":
            self.dashboard.refresh()
        elif page == "history":
            self.history.refresh()
        elif page == "profiles":
            self.profiles.refresh()
        elif page == "settings":
            self.settings.refresh_profiles()
            self.settings._load_values()
        elif page == "export":
            self.export_center._refresh_table()
        self.notify("Page refreshed.", "info")

    def _open_data_folder(self) -> None:
        """Reveal the storage folder in the system file manager."""

        folder = Path(STORAGE_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Folder unavailable", f"Could not open {folder}:\n{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------ studio menu bridge
    def _open_image(self) -> None:
        self.navigate("studio")
        self.studio._choose_file()

    def _save_project(self) -> None:
        self.navigate("studio")
        self.studio._save_project(ask_filename=True)

    def _save_project_as(self) -> None:
        self.navigate("studio")
        self.studio._save_project_as()

    def _close_project(self) -> None:
        self.studio._close_project()

    def _revert_project(self) -> None:
        self.navigate("studio")
        self.studio._revert_project()

    def _export_current(self) -> None:
        self.navigate("studio")
        self.studio._export()

    def _undo(self) -> None:
        self.studio._undo()

    def _redo(self) -> None:
        self.studio._redo()

    def _paste_image(self) -> None:
        self.navigate("studio")
        self.studio._paste_image()

    def _detect_document(self) -> None:
        self.navigate("studio")
        self.studio._start_detection()

    def _reset_corners(self) -> None:
        self.navigate("studio")
        self.studio._reset_corners()

    def _reset_to_original(self) -> None:
        self.navigate("studio")
        self.studio._reset_to_original()

    def _rotate(self, degrees: int) -> None:
        self.navigate("studio")
        self.studio._rotate_by(degrees)

    def _load_recent_files(self) -> None:
        """Load recent files from settings."""
        recent = self.ctx.config.get("recent_files", [])
        if isinstance(recent, list):
            self._recent_files = [str(p) for p in recent if p and Path(p).exists()][:10]
        else:
            self._recent_files = []

    def _save_recent_files(self) -> None:
        """Save recent files to settings."""
        self.ctx.config.set("recent_files", self._recent_files)
        self.ctx.config.save()

    def _add_recent_file(self, path: str) -> None:
        """Add a file to the recent files list."""
        path = str(Path(path).resolve())
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:10]
        self._save_recent_files()
        self._update_recent_files_menu()

    def _update_recent_files_menu(self) -> None:
        """Update the recent files submenu."""
        if self._recent_files_menu is None:
            return
        self._recent_files_menu.clear()
        if not self._recent_files:
            action = QAction("No recent files", self)
            action.setEnabled(False)
            self._recent_files_menu.addAction(action)
            return
        for i, path in enumerate(self._recent_files):
            name = Path(path).name
            action = QAction(f"{i + 1}. {name}", self)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self._open_recent_file(p))
            self._recent_files_menu.addAction(action)
        self._recent_files_menu.addSeparator()
        clear_action = QAction("Clear recent files", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self._recent_files_menu.addAction(clear_action)

    def _open_recent_file(self, path: str) -> None:
        """Open a recent file."""
        if not Path(path).exists():
            QMessageBox.warning(self, "File not found", f"The file no longer exists:\n{path}")
            self._recent_files.remove(path)
            self._save_recent_files()
            self._update_recent_files_menu()
            return
        # Check if it's a project file or image
        if path.endswith(".json"):
            self._open_project_file(path)
        else:
            self.navigate("studio")
            if self.studio.load_image_path(path):
                self._add_recent_file(path)
                self.notify(f"Opened '{Path(path).name}'.", "info")

    def _open_project_file(self, path: str) -> None:
        """Open a project file from recent files."""
        try:
            record = self.ctx.projects.open_project_file(path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Cannot open project", f"The project file could not be read:\n{exc}")
            return
        self.navigate("studio")
        if self.studio.load_project(record):
            self._add_recent_file(path)
            self.notify(f"Opened project '{record.name}'.", "success")

    def _clear_recent_files(self) -> None:
        """Clear the recent files list."""
        self._recent_files.clear()
        self._save_recent_files()
        self._update_recent_files_menu()

    def _wire_signals(self) -> None:
        self.dashboard.newCorrectionRequested.connect(self._new_correction)
        self.dashboard.batchRequested.connect(lambda: self.navigate("batch"))
        self.dashboard.openProjectRequested.connect(self._open_project)
        self.dashboard.profilesRequested.connect(lambda: self.navigate("profiles"))
        self.dashboard.recordRequested.connect(self._open_record)
        self.dashboard.historyFilteredRequested.connect(self._open_history_filtered)

        self.studio.notifyRequested.connect(self.notify)
        self.studio.historyChanged.connect(self._refresh_history_dependent)
        self.studio.batchFilesRequested.connect(self._add_batch_files)

        self.batch.notifyRequested.connect(self.notify)
        self.batch.historyChanged.connect(self._refresh_history_dependent)
        self.batch.reviewRequested.connect(self._review_in_studio)

        self.profiles.notifyRequested.connect(self.notify)
        self.profiles.notifyRequested.connect(lambda _t, _k: self._refresh_profiles())
        self.history.notifyRequested.connect(self.notify)
        self.history.historyChanged.connect(self._refresh_history_dependent)
        self.history.openProjectRequested.connect(self._open_record)
        self.export_center.historyChanged.connect(self._refresh_history_dependent)
        self.settings.notifyRequested.connect(self.notify)
        self.settings.settingsChanged.connect(self._on_settings_changed)
        self.settings.historyChanged.connect(self._refresh_history_dependent)

        self.ctx.profilesChanged.connect(self._refresh_profiles)
        self.ctx.settingsChanged.connect(self._on_settings_changed)
        # Page-aware menu enablement.
        self.studio.documentStateChanged.connect(self._update_menu_state)

    # -------------------------------------------------------------- navigation
    def navigate(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self._nav_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        if key == "dashboard":
            self.dashboard.refresh()
        elif key == "history":
            self.history.refresh()
        elif key == "profiles":
            self.profiles.refresh()
        elif key == "settings":
            self.settings.refresh_profiles()
        elif key == "studio":
            # Check for draft recovery on first visit
            if not getattr(self, "_studio_draft_checked", False):
                self._studio_draft_checked = True
                self.studio.check_and_recover_draft()
        self._update_menu_state()

    def notify(self, text: str, kind: str = "info") -> None:
        self.notifications.show_message(text, kind)

    # ----------------------------------------------------------------- actions
    def _new_correction(self) -> None:
        self.navigate("studio")
        folder = str(self.ctx.config.get("project_dir"))
        result = QFileDialog.getOpenFileName(self, "Open a document photo", folder, "Images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)")
        if result and result[0]:
            self.studio.load_image_path(result[0])
            self._add_recent_file(result[0])

    def _open_project(self) -> None:
        folder = str(self.ctx.config.get("project_dir"))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", folder, "Project files (*.json);;All files (*.*)"
        )
        if not path:
            return
        self._open_project_file(path)

    def _open_record(self, record_id: str) -> None:
        record = self.ctx.repository.get_project(record_id)
        if record is None:
            QMessageBox.warning(self, "Project not found", "This history record no longer exists.")
            return
        self.navigate("studio")
        if self.studio.load_project(record):
            if record.source_path:
                self._add_recent_file(record.source_path)
            self.notify(f"Opened '{record.name}'.", "info")

    def _open_history_filtered(self, filter_type: str) -> None:
        """Open history page with a specific filter."""
        self.navigate("history")
        # Apply filter to history page
        if filter_type == "success":
            self.history.search_edit.setText("status:success")
        elif filter_type == "failed":
            self.history.search_edit.setText("status:failed")
        else:
            self.history.search_edit.clear()
        self.history.refresh()

    def _review_in_studio(self, path: str) -> None:
        self.navigate("studio")
        if self.studio.load_image_path(path):
            self._add_recent_file(path)
            self.notify("Opened in the Correction Studio.", "info")

    def _add_batch_files(self, paths: list) -> None:
        self.batch.add_files(list(paths))
        self.notify(f"Added {len(paths)} file(s) to Batch Processing.", "info")

    # ------------------------------------------------------------- maintenance
    def _refresh_history_dependent(self) -> None:
        self.dashboard.refresh()
        self.history.refresh()

    def _refresh_profiles(self) -> None:
        self.studio._refresh_profiles()
        self.batch._refresh_profiles()
        self.settings.refresh_profiles()

    def _on_settings_changed(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, str(self.ctx.config.get("theme", "light")))
        self.settings._load_values()
        self.dashboard.refresh()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
            "Perspective correction for ID cards, driving licences, Istimara, passports "
            "and other documents.<br><br>"
            "All processing happens locally. Document images are never uploaded or transmitted.<br><br>"
            "Physical dimensions can be calibrated in Document Profiles.",
        )

    def _show_shortcuts(self) -> None:
        """Show keyboard shortcuts help dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard Shortcuts")
        dialog.resize(500, 400)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        shortcuts = [
            ("Ctrl+N", "New correction"),
            ("Ctrl+O", "Open image (Studio)"),
            ("Ctrl+Shift+O", "Open project"),
            ("Ctrl+V", "Paste image from clipboard"),
            ("Ctrl+Z", "Undo"),
            ("Ctrl+Shift+Z / Ctrl+Y", "Redo"),
            ("Ctrl+S", "Save project"),
            ("Ctrl+Shift+S", "Save project as…"),
            ("Ctrl+W", "Close project"),
            ("Ctrl+E", "Export"),
            ("Ctrl+D", "Detect document"),
            ("F5", "Refresh the current page"),
            ("Ctrl+Q", "Exit"),
            ("F1", "Show this help"),
            ("Mouse wheel", "Zoom at pointer"),
            ("Arrow keys", "Nudge selected corner 1 px"),
            ("Shift+Arrow keys", "Nudge selected corner 10 px"),
            ("1–4", "Select corner TL / TR / BR / BL"),
            ("Drag empty area / Middle mouse", "Pan"),
        ]

        table.setRowCount(len(shortcuts))
        for row, (shortcut, action) in enumerate(shortcuts):
            table.setItem(row, 0, QTableWidgetItem(shortcut))
            table.setItem(row, 1, QTableWidgetItem(action))
            table.item(row, 0).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        table.resizeColumnsToContents()
        layout.addWidget(table)

        close_button = QPushButton("Close")
        close_button.setObjectName("Primary")
        close_button.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        dialog.exec()

    def closeEvent(self, event) -> None:
        # Ask before discarding unsaved studio work. Cancelling keeps the app
        # open, so the check must run before any worker is stopped.
        try:
            dirty = self.studio.has_unsaved_changes()
        except Exception:  # noqa: BLE001 - never block closing on a probe error
            dirty = False
        if dirty:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                "The document in the Correction Studio has unsaved changes.\n\n"
                "Close FlatScan anyway and discard them?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                if not self.studio._save_project():
                    # The save failed (it already reported why); keep the app
                    # open rather than destroying the user's work.
                    event.ignore()
                    return
        # Each shutdown gets its own try/except: a failure in one worker must
        # not orphan the other running threads at teardown.
        for shutdown in (self.studio.shutdown, self.batch.shutdown, self.export_center.shutdown):
            try:
                shutdown()
            except Exception:  # noqa: BLE001 - never block closing
                pass
        if self.ctx.config.get("cleanup_temp_on_exit", True):
            try:
                self.ctx.cleanup_temp(2)
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)
