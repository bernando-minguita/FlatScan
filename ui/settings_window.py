"""Settings: appearance, defaults, directories, history and behaviour."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import DPI_CHOICES, OUTPUT_FORMATS, OVERWRITE_POLICIES
from app.context import AppContext
from ui.icons import make_icon


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 15, 18, 18)
    layout.setSpacing(10)
    return frame, layout


class SettingsPage(QWidget):
    settingsChanged = Signal()
    historyChanged = Signal()
    notifyRequested = Signal(str, str)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("Transparent")
        root = QVBoxLayout(container)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QVBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Defaults are stored locally and loaded at the next start.")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # appearance
        appearance_card, appearance_layout = _card()
        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName("SectionTitle")
        appearance_layout.addWidget(appearance_title)
        appearance_form = QFormLayout()
        appearance_form.setSpacing(9)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        theme_row = QHBoxLayout()
        theme_row.setSpacing(6)
        theme_row.addWidget(self.theme_combo, 1)
        self.theme_preview_button = QPushButton("Preview")
        self.theme_preview_button.setToolTip("Preview the selected theme")
        self.theme_preview_button.clicked.connect(self._preview_theme)
        theme_row.addWidget(self.theme_preview_button)
        appearance_form.addRow("Theme", theme_row)
        appearance_layout.addLayout(appearance_form)
        root.addWidget(appearance_card)

        # defaults
        defaults_card, defaults_layout = _card()
        defaults_title = QLabel("Processing defaults")
        defaults_title.setObjectName("SectionTitle")
        defaults_layout.addWidget(defaults_title)
        defaults_form = QFormLayout()
        defaults_form.setSpacing(9)
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Default document profile for new corrections")
        self.dpi_combo = QComboBox()
        self.dpi_combo.setToolTip("Default output DPI for new corrections")
        self.dpi_combo.addItems([str(value) for value in DPI_CHOICES])
        self.dpi_combo.setEditable(True)
        self.format_combo = QComboBox()
        self.format_combo.setToolTip("Default output format for new corrections")
        self.format_combo.addItems(list(OUTPUT_FORMATS))
        self.quality_spin = QSpinBox()
        self.quality_spin.setToolTip("Default JPEG quality (50-100)")
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setSuffix(" %")
        self.sensitivity_spin = QSpinBox()
        self.sensitivity_spin.setToolTip("Default detection sensitivity (0-100%). Lower = stricter")
        self.sensitivity_spin.setRange(0, 100)
        self.sensitivity_spin.setSuffix(" %")
        self.interpolation_combo = QComboBox()
        self.interpolation_combo.setToolTip("Default interpolation method for perspective correction")
        self.interpolation_combo.addItems(["Nearest", "Linear", "Cubic", "Lanczos"])
        self.auto_enhance_check = QCheckBox("Apply automatic enhancement to new images")
        self.auto_enhance_check.setToolTip("Automatically apply enhancement when loading new images")
        self.template_edit = QLineEdit()
        self.template_edit.setToolTip("Filename template. Tokens: {name} {profile} {side} {date} {time} {dpi} {index}")
        self.policy_combo = QComboBox()
        self.policy_combo.setToolTip("Default action when output file already exists")
        for value, label in OVERWRITE_POLICIES:
            self.policy_combo.addItem(label, value)
        defaults_form.addRow("Default profile", self.profile_combo)
        defaults_form.addRow("Default DPI", self.dpi_combo)
        defaults_form.addRow("Default format", self.format_combo)
        defaults_form.addRow("JPEG quality", self.quality_spin)
        defaults_form.addRow("Detection sensitivity", self.sensitivity_spin)
        defaults_form.addRow("Interpolation", self.interpolation_combo)
        defaults_form.addRow("Filename template", self.template_edit)
        defaults_form.addRow("If output exists", self.policy_combo)
        defaults_form.addRow("", self.auto_enhance_check)
        defaults_layout.addLayout(defaults_form)
        root.addWidget(defaults_card)

        # directories
        directories_card, directories_layout = _card()
        directories_title = QLabel("Directories")
        directories_title.setObjectName("SectionTitle")
        directories_layout.addWidget(directories_title)
        self.project_dir_edit = QLineEdit()
        self.project_dir_edit.setToolTip("Folder where project JSON files are saved")
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setToolTip("Default folder for exported documents")
        self.temp_dir_edit = QLineEdit()
        self.temp_dir_edit.setToolTip("Folder for temporary files (PDF imports, etc.)")
        self.thumbnail_dir_edit = QLineEdit()
        self.thumbnail_dir_edit.setToolTip("Folder for thumbnail cache")
        for label, edit in (
            ("Project files", self.project_dir_edit),
            ("Exported documents", self.output_dir_edit),
            ("Temporary files", self.temp_dir_edit),
            ("Thumbnails", self.thumbnail_dir_edit),
        ):
            button = QPushButton()
            button.setIcon(make_icon("folder", "#475569", 16))
            button.setToolTip("Choose folder")
            button.clicked.connect(lambda _checked=False, e=edit: self._browse(e))
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(edit, 1)
            row.addWidget(button)
            directories_layout.addWidget(QLabel(label))
            directories_layout.addLayout(row)
        directory_hint = QLabel(
            "Temporary files are used for PDF import. The original images are never modified."
        )
        directory_hint.setObjectName("Hint")
        directory_hint.setWordWrap(True)
        directories_layout.addWidget(directory_hint)
        root.addWidget(directories_card)

        # history & cleanup
        history_card, history_layout = _card()
        history_title = QLabel("History and storage")
        history_title.setObjectName("SectionTitle")
        history_layout.addWidget(history_title)
        history_form = QFormLayout()
        history_form.setSpacing(9)
        self.retention_spin = QSpinBox()
        self.retention_spin.setToolTip("Automatically delete history records older than this many days (0 = keep forever)")
        self.retention_spin.setRange(0, 3650)
        self.retention_spin.setSuffix(" days")
        self.retention_spin.setSpecialValueText("Keep forever")
        history_form.addRow("History retention", self.retention_spin)
        self.cleanup_temp_check = QCheckBox("Clean temporary files when the application closes")
        self.cleanup_temp_check.setToolTip("Remove temporary files (PDF imports) on application exit")
        history_form.addRow("", self.cleanup_temp_check)
        history_layout.addLayout(history_form)
        cleanup_row = QHBoxLayout()
        self.purge_button = QPushButton("Purge old history")
        self.purge_button.setToolTip("Delete history records older than the retention period")
        self.purge_button.clicked.connect(self._purge_history)
        self.clear_history_button = QPushButton("Clear all history")
        self.clear_history_button.setObjectName("DangerButton")
        self.clear_history_button.setToolTip("Delete all history records (exported files are kept)")
        self.clear_history_button.clicked.connect(self._clear_history)
        self.clean_temp_button = QPushButton("Clean temporary files")
        self.clean_temp_button.setToolTip("Remove all temporary files now")
        self.clean_temp_button.clicked.connect(self._clean_temp)
        cleanup_row.addWidget(self.purge_button)
        cleanup_row.addWidget(self.clear_history_button)
        cleanup_row.addStretch(1)
        cleanup_row.addWidget(self.clean_temp_button)
        history_layout.addLayout(cleanup_row)
        root.addWidget(history_card)

        # behaviour
        behaviour_card, behaviour_layout = _card()
        behaviour_title = QLabel("Behaviour and confirmations")
        behaviour_title.setObjectName("SectionTitle")
        behaviour_layout.addWidget(behaviour_title)
        self.batch_auto_detect_check = QCheckBox("Detect documents automatically in batch processing")
        self.batch_auto_detect_check.setToolTip("Run automatic detection for each image in batch processing")
        self.batch_continue_check = QCheckBox("Continue a batch when one file fails")
        self.batch_continue_check.setToolTip("Don't stop the entire batch if a single file fails")
        self.confirm_overwrite_check = QCheckBox("Confirm before replacing an existing output file")
        self.confirm_overwrite_check.setToolTip("Ask before overwriting existing files when policy is 'replace'")
        self.confirm_delete_check = QCheckBox("Confirm before deleting history records or profiles")
        self.confirm_delete_check.setToolTip("Show confirmation dialog before deleting records or profiles")
        self.quality_warnings_check = QCheckBox("Show image quality warnings")
        self.quality_warnings_check.setToolTip("Display quality analysis warnings in the Correction Studio")
        for check in (
            self.batch_auto_detect_check,
            self.batch_continue_check,
            self.confirm_overwrite_check,
            self.confirm_delete_check,
            self.quality_warnings_check,
        ):
            behaviour_layout.addWidget(check)
        root.addWidget(behaviour_card)

        buttons = QHBoxLayout()
        self.reset_button = QPushButton("Restore defaults")
        self.reset_button.setObjectName("Ghost")
        self.reset_button.clicked.connect(self._reset_defaults)
        self.save_button = QPushButton("Save settings")
        self.save_button.setObjectName("Primary")
        self.save_button.setIcon(make_icon("save", "#FFFFFF", 15))
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
        root.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ----------------------------------------------------------------- values
    def refresh_profiles(self) -> None:
        current = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Use the database default", None)
        for profile in self.ctx.profiles():
            self.profile_combo.addItem(profile.name, profile.id)
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def _load_values(self) -> None:
        config = self.ctx.config
        self.refresh_profiles()
        theme = str(config.get("theme", "light"))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(theme)))
        self.profile_combo.setCurrentIndex(
            max(0, self.profile_combo.findData(config.get("default_profile_id")))
        )
        self.dpi_combo.setCurrentText(str(config.get("default_dpi", 300)))
        fmt = str(config.get("default_format", "JPEG"))
        self.format_combo.setCurrentText(fmt if fmt in OUTPUT_FORMATS else "JPEG")
        self.quality_spin.setValue(int(config.get("jpeg_quality", 95)))
        self.sensitivity_spin.setValue(int(float(config.get("detection_sensitivity", 0.5)) * 100))
        self.interpolation_combo.setCurrentText(str(config.get("interpolation", "Cubic")))
        self.auto_enhance_check.setChecked(bool(config.get("auto_enhance", False)))
        self.template_edit.setText(str(config.get("filename_template", "{name}_{profile}")))
        policy = str(config.get("overwrite_policy", "rename"))
        index = self.policy_combo.findData(policy)
        self.policy_combo.setCurrentIndex(max(0, index))
        self.project_dir_edit.setText(str(config.get("project_dir")))
        self.output_dir_edit.setText(str(config.get("output_dir")))
        self.temp_dir_edit.setText(str(config.get("temp_dir")))
        self.thumbnail_dir_edit.setText(str(config.get("thumbnail_dir")))
        self.retention_spin.setValue(int(config.get("history_retention_days", 0)))
        self.cleanup_temp_check.setChecked(bool(config.get("cleanup_temp_on_exit", True)))
        self.batch_auto_detect_check.setChecked(bool(config.get("batch_auto_detect", True)))
        self.batch_continue_check.setChecked(bool(config.get("batch_continue_on_error", True)))
        self.confirm_overwrite_check.setChecked(bool(config.get("confirm_overwrite", True)))
        self.confirm_delete_check.setChecked(bool(config.get("confirm_delete", True)))
        self.quality_warnings_check.setChecked(bool(config.get("show_quality_warnings", True)))
        self.purge_button.setEnabled(self.retention_spin.value() > 0)

    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
        if folder:
            edit.setText(folder)

    def _preview_theme(self) -> None:
        """Show a preview dialog for the selected theme."""
        theme = self.theme_combo.currentData()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Theme Preview — {theme.capitalize()}")
        dialog.resize(400, 300)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Apply the theme to the dialog
        from ui.styles.theme import apply_theme
        apply_theme(dialog, theme)

        # Preview content
        title = QLabel(f"{theme.capitalize()} Theme Preview")
        title.setObjectName("PageTitle")
        subtitle = QLabel("This is how the application will look with the selected theme.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Sample UI elements
        from PySide6.QtWidgets import QComboBox, QLineEdit, QSpinBox, QCheckBox, QPushButton
        sample_card, sample_layout = _card()
        sample_title = QLabel("Sample Controls")
        sample_title.setObjectName("SectionTitle")
        sample_layout.addWidget(sample_title)

        sample_combo = QComboBox()
        sample_combo.addItems(["Option 1", "Option 2", "Option 3"])
        sample_layout.addWidget(QLabel("Combo Box:"))
        sample_layout.addWidget(sample_combo)

        sample_edit = QLineEdit()
        sample_edit.setPlaceholderText("Sample text input")
        sample_layout.addWidget(QLabel("Text Input:"))
        sample_layout.addWidget(sample_edit)

        sample_spin = QSpinBox()
        sample_spin.setRange(0, 100)
        sample_spin.setValue(50)
        sample_spin.setSuffix(" %")
        sample_layout.addWidget(QLabel("Spin Box:"))
        sample_layout.addWidget(sample_spin)

        sample_check = QCheckBox("Sample checkbox option")
        sample_check.setChecked(True)
        sample_layout.addWidget(sample_check)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        primary_btn = QPushButton("Primary Button")
        primary_btn.setObjectName("Primary")
        secondary_btn = QPushButton("Secondary Button")
        secondary_btn.setObjectName("Secondary")
        ghost_btn = QPushButton("Ghost Button")
        ghost_btn.setObjectName("Ghost")
        danger_btn = QPushButton("Danger Button")
        danger_btn.setObjectName("DangerButton")
        button_row.addWidget(primary_btn)
        button_row.addWidget(secondary_btn)
        button_row.addWidget(ghost_btn)
        button_row.addWidget(danger_btn)
        sample_layout.addLayout(button_row)

        layout.addWidget(sample_card)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(dialog.accept)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def _save(self) -> None:
        config = self.ctx.config
        try:
            dpi = int(float(self.dpi_combo.currentText()))
        except ValueError:
            QMessageBox.warning(self, "Invalid DPI", "Enter a numeric DPI value.")
            return
        if dpi < 72 or dpi > 1200:
            QMessageBox.warning(self, "Invalid DPI", "DPI must be between 72 and 1200.")
            return
        for edit, key in (
            (self.project_dir_edit, "project_dir"),
            (self.output_dir_edit, "output_dir"),
            (self.temp_dir_edit, "temp_dir"),
            (self.thumbnail_dir_edit, "thumbnail_dir"),
        ):
            folder = Path(edit.text().strip())
            if not str(folder):
                QMessageBox.warning(self, "Invalid folder", "Choose a folder for every directory.")
                return
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "Folder not usable", f"{folder}\n{exc}")
                return
        config.update(
            {
                "theme": self.theme_combo.currentData(),
                "default_profile_id": self.profile_combo.currentData(),
                "default_dpi": dpi,
                "default_format": self.format_combo.currentText(),
                "jpeg_quality": self.quality_spin.value(),
                "detection_sensitivity": self.sensitivity_spin.value() / 100.0,
                "interpolation": self.interpolation_combo.currentText(),
                "auto_enhance": self.auto_enhance_check.isChecked(),
                "filename_template": self.template_edit.text().strip() or "{name}_{profile}",
                "overwrite_policy": self.policy_combo.currentData(),
                "project_dir": self.project_dir_edit.text().strip(),
                "output_dir": self.output_dir_edit.text().strip(),
                "temp_dir": self.temp_dir_edit.text().strip(),
                "thumbnail_dir": self.thumbnail_dir_edit.text().strip(),
                "history_retention_days": self.retention_spin.value(),
                "cleanup_temp_on_exit": self.cleanup_temp_check.isChecked(),
                "batch_auto_detect": self.batch_auto_detect_check.isChecked(),
                "batch_continue_on_error": self.batch_continue_check.isChecked(),
                "confirm_overwrite": self.confirm_overwrite_check.isChecked(),
                "confirm_delete": self.confirm_delete_check.isChecked(),
                "show_quality_warnings": self.quality_warnings_check.isChecked(),
            }
        )
        self.ctx.save_settings()
        self.settingsChanged.emit()
        self.notifyRequested.emit("Settings saved.", "success")

    def _reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore settings defaults",
            "Reset every setting to its factory default? Processing history and profiles are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.config.reset()
        self._load_values()
        self.ctx.save_settings()
        self.settingsChanged.emit()
        self.notifyRequested.emit("Settings restored to defaults.", "info")

    # --------------------------------------------------------------- cleanup
    def _purge_history(self) -> None:
        days = self.retention_spin.value()
        if days <= 0:
            QMessageBox.information(
                self, "No retention", "Set a retention period before purging old records."
            )
            return
        answer = QMessageBox.question(
            self,
            "Purge history",
            f"Delete history records older than {days} days? Exported files are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.ctx.projects.purge_old(days)
        self.historyChanged.emit()
        self.notifyRequested.emit(f"Removed {removed} old record(s).", "info")

    def _clear_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear all history",
            "Delete every processing history record? Images and exported files on disk are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        count = self.ctx.projects.clear_history()
        self.historyChanged.emit()
        self.notifyRequested.emit(f"Cleared {count} history record(s).", "info")

    def _clean_temp(self) -> None:
        removed = self.ctx.cleanup_temp(0)
        self.notifyRequested.emit(f"Removed {removed} temporary file(s).", "info")
