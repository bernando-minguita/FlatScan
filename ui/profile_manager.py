"""Document profile manager: physical size, DPI, format and defaults."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import OUTPUT_FORMATS
from app.context import AppContext
from core import dimension_calculator
from database.models import DocumentProfile
from ui.icons import make_icon


class AspectRatioPreview(QWidget):
    """Small widget showing a visual preview of the document's aspect ratio."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setMinimumWidth(120)
        self._width_mm = 85.6
        self._height_mm = 53.98
        self._orientation = "landscape"

    def set_dimensions(self, width_mm: float, height_mm: float, orientation: str = "") -> None:
        self._width_mm = width_mm
        self._height_mm = height_mm
        if orientation:
            self._orientation = orientation
        else:
            self._orientation = "landscape" if width_mm > height_mm else ("portrait" if height_mm > width_mm else "square")
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Calculate aspect ratio
        if self._height_mm <= 0:
            return
        aspect = self._width_mm / self._height_mm

        # Determine drawing rect (centered, max 100px in either dimension)
        max_dim = 100
        margin = 10
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin

        if aspect >= 1:
            draw_w = min(max_dim, avail_w)
            draw_h = draw_w / aspect
            if draw_h > avail_h:
                draw_h = min(max_dim, avail_h)
                draw_w = draw_h * aspect
        else:
            draw_h = min(max_dim, avail_h)
            draw_w = draw_h * aspect
            if draw_w > avail_w:
                draw_w = min(max_dim, avail_w)
                draw_h = draw_w / aspect

        x = (self.width() - draw_w) / 2
        y = (self.height() - draw_h) / 2

        # Draw background card
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        painter.setBrush(QBrush(QColor("#F8FAFC")))
        painter.drawRoundedRect(int(x), int(y), int(draw_w), int(draw_h), 4, 4)

        # Draw border
        painter.setPen(QPen(QColor("#2563EB"), 2))
        painter.setBrush(QBrush())
        painter.drawRoundedRect(int(x), int(y), int(draw_w), int(draw_h), 4, 4)

        # Draw orientation label
        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#64748B"))
        label = self._orientation.capitalize()
        if abs(aspect - 1.0) < 0.02:
            label = "Square"
        elif aspect > 1:
            label = "Landscape"
        else:
            label = "Portrait"
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -4),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            f"{label}  ({self._width_mm:g} × {self._height_mm:g} mm)"
        )


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    return frame, layout


class ProfileManagerPage(QWidget):
    notifyRequested = Signal(str, str)

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self._profiles: list[DocumentProfile] = []
        self._current_id: int | None = None
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Document Profiles")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Physical size drives the output pixel dimensions. Measure your own documents and "
            "calibrate the values — Saudi documents vary between issues."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.default_chip = QLabel("")
        self.default_chip.setObjectName("ChipSuccess")
        header.addWidget(self.default_chip)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)

        list_card, list_layout = _card()
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Profiles"))
        list_header.addStretch(1)
        self.new_button = QPushButton("New")
        self.new_button.setIcon(make_icon("add", "#334155", 15))
        self.new_button.clicked.connect(self._new_profile)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.setObjectName("Ghost")
        self.duplicate_button.clicked.connect(self._duplicate)
        list_header.addWidget(self.new_button)
        list_header.addWidget(self.duplicate_button)
        list_layout.addLayout(list_header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Size (mm)", "DPI", "Format", "Default"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.table, 1)

        restore_row = QHBoxLayout()
        self.restore_button = QPushButton("Restore defaults")
        self.restore_button.setObjectName("Ghost")
        self.restore_button.clicked.connect(self._restore_defaults)
        self.default_button = QPushButton("Set as default")
        self.default_button.clicked.connect(self._set_default)
        restore_row.addWidget(self.restore_button)
        restore_row.addStretch(1)
        restore_row.addWidget(self.default_button)
        list_layout.addLayout(restore_row)
        content.addWidget(list_card, 3)

        editor_card, editor_layout = _card()
        editor_layout.addWidget(QLabel("Profile details"))
        self.name_edit = QLineEdit()
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(64)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 2000.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" mm")
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1.0, 2000.0)
        self.height_spin.setDecimals(2)
        self.height_spin.setSuffix(" mm")
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setSuffix(" DPI")
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(OUTPUT_FORMATS))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(50, 100)
        self.quality_spin.setSuffix(" %")
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems(["landscape", "portrait", "square"])
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("e.g. iqama")
        self.active_check = QCheckBox("Profile is active in the pickers")

        form = QFormLayout()
        form.setSpacing(9)
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.description_edit)
        form.addRow("Physical width", self.width_spin)
        form.addRow("Physical height", self.height_spin)
        form.addRow("Output DPI", self.dpi_spin)
        form.addRow("Default format", self.format_combo)
        form.addRow("Image quality", self.quality_spin)
        form.addRow("Default orientation", self.orientation_combo)
        form.addRow("Filename prefix", self.prefix_edit)
        form.addRow("", self.active_check)
        editor_layout.addLayout(form)

        self.pixel_label = QLabel("—")
        self.pixel_label.setObjectName("Hint")
        self.pixel_label.setWordWrap(True)
        editor_layout.addWidget(self.pixel_label)

        # Aspect ratio visual preview
        self.aspect_preview = AspectRatioPreview()
        editor_layout.addWidget(self.aspect_preview)

        for spin in (self.width_spin, self.height_spin, self.dpi_spin):
            spin.valueChanged.connect(self._update_pixel_label)

        buttons = QHBoxLayout()
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setIcon(make_icon("trash", "#B91C1C", 15))
        self.delete_button.clicked.connect(self._delete)
        self.save_button = QPushButton("Save profile")
        self.save_button.setObjectName("Primary")
        self.save_button.setIcon(make_icon("save", "#FFFFFF", 15))
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        editor_layout.addLayout(buttons)
        content.addWidget(editor_card, 2)
        root.addLayout(content, 1)
        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self.name_edit,
            self.description_edit,
            self.width_spin,
            self.height_spin,
            self.dpi_spin,
            self.format_combo,
            self.quality_spin,
            self.orientation_combo,
            self.prefix_edit,
            self.active_check,
            self.save_button,
            self.delete_button,
            self.default_button,
        ):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        selected = self._current_id
        self._profiles = self.ctx.profiles()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for profile in self._profiles:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(profile.name)
            name_item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(
                row, 1, QTableWidgetItem(f"{profile.width_mm:g} × {profile.height_mm:g}")
            )
            self.table.setItem(row, 2, QTableWidgetItem(str(profile.dpi)))
            self.table.setItem(row, 3, QTableWidgetItem(profile.format))
            self.table.setItem(row, 4, QTableWidgetItem("Yes" if profile.is_default else ""))
        self.table.blockSignals(False)

        default = next((p for p in self._profiles if p.is_default), None)
        self.default_chip.setText(f"Default: {default.name}" if default else "No default profile")

        if selected is not None:
            index = next(
                (i for i, p in enumerate(self._profiles) if p.id == selected), None
            )
        else:
            index = 0 if self._profiles else None
        if index is not None and self._profiles:
            self.table.selectRow(index)
            self._load_profile(self._profiles[index])
        else:
            self._set_editor_enabled(False)

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if 0 <= row < len(self._profiles):
            self._load_profile(self._profiles[row])

    def _load_profile(self, profile: DocumentProfile) -> None:
        self._current_id = profile.id
        self._set_editor_enabled(True)
        self.name_edit.setText(profile.name)
        self.description_edit.setPlainText(profile.description)
        self.width_spin.setValue(profile.width_mm)
        self.height_spin.setValue(profile.height_mm)
        self.dpi_spin.setValue(profile.dpi)
        self.format_combo.setCurrentText(profile.format if profile.format in OUTPUT_FORMATS else "JPEG")
        self.quality_spin.setValue(profile.quality)
        self.orientation_combo.setCurrentText(profile.orientation or "landscape")
        self.prefix_edit.setText(profile.filename_prefix)
        self.active_check.setChecked(profile.active)
        self.delete_button.setEnabled(not profile.builtin)
        self.default_button.setEnabled(not profile.is_default)
        self.delete_button.setToolTip(
            "Built-in profiles cannot be deleted — deactivate it instead"
            if profile.builtin
            else "Delete this custom profile"
        )
        self._update_pixel_label()

    def _update_pixel_label(self) -> None:
        try:
            width, height = dimension_calculator.output_pixel_size(
                self.width_spin.value(), self.height_spin.value(), self.dpi_spin.value()
            )
            self.pixel_label.setText(
                f"Output at {self.dpi_spin.value()} DPI: {width} × {height} px  ·  "
                f"{self.width_spin.value():g} × {self.height_spin.value():g} mm"
            )
            # Update aspect ratio preview
            orientation = self.orientation_combo.currentText()
            self.aspect_preview.set_dimensions(
                self.width_spin.value(), self.height_spin.value(), orientation
            )
        except dimension_calculator.DimensionError as exc:
            self.pixel_label.setText(str(exc))

    # --------------------------------------------------------------- actions
    def _new_profile(self) -> None:
        profile = DocumentProfile(
            name="New profile",
            description="",
            width_mm=85.6,
            height_mm=53.98,
            dpi=300,
            format="JPEG",
            quality=95,
            orientation="landscape",
            filename_prefix="document",
            active=True,
        )
        try:
            new_id = self.ctx.repository.create_profile(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not create profile", str(exc))
            return
        self._current_id = new_id
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit("New profile created. Edit its measurements and save.", "info")

    def _duplicate(self) -> None:
        if self._current_id is None:
            return
        try:
            new_id = self.ctx.repository.duplicate_profile(self._current_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not duplicate profile", str(exc))
            return
        self._current_id = new_id
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit("Profile duplicated.", "success")

    def _delete(self) -> None:
        if self._current_id is None:
            return
        profile = self.ctx.repository.get_profile(self._current_id)
        if profile is None:
            return
        if profile.builtin:
            QMessageBox.information(
                self,
                "Built-in profile",
                "Built-in profiles cannot be deleted. Deactivate the profile instead.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the custom profile '{profile.name}'? Existing projects keep their data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.ctx.repository.delete_profile(profile.id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not delete profile", str(exc))
            return
        self._current_id = None
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit("Profile deleted.", "info")

    def _save(self) -> None:
        if self._current_id is None:
            return
        try:
            dimension_calculator.validate_dimensions(
                self.width_spin.value(), self.height_spin.value(), self.dpi_spin.value()
            )
        except dimension_calculator.DimensionError as exc:
            QMessageBox.warning(self, "Invalid measurements", str(exc))
            return
        profile = self.ctx.repository.get_profile(self._current_id)
        if profile is None:
            return
        profile.name = self.name_edit.text().strip()
        profile.description = self.description_edit.toPlainText().strip()
        profile.width_mm = self.width_spin.value()
        profile.height_mm = self.height_spin.value()
        profile.dpi = self.dpi_spin.value()
        profile.format = self.format_combo.currentText()
        profile.quality = self.quality_spin.value()
        profile.orientation = self.orientation_combo.currentText()
        profile.filename_prefix = self.prefix_edit.text().strip()
        profile.active = self.active_check.isChecked()
        if not profile.name:
            QMessageBox.warning(self, "Name required", "Give the profile a name before saving.")
            return
        try:
            self.ctx.repository.update_profile(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not save profile", str(exc))
            return
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit(f"Profile '{profile.name}' saved.", "success")

    def _set_default(self) -> None:
        if self._current_id is None:
            return
        try:
            self.ctx.repository.set_default_profile(self._current_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not set the default", str(exc))
            return
        self.ctx.config.set("default_profile_id", self._current_id)
        self.ctx.save_settings()
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit("Default profile updated.", "success")

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore default profiles",
            "Re-create the built-in Saudi document profiles with their shipped measurements? "
            "Custom profiles are kept; any edits to built-in profiles are replaced.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self.ctx.repository.restore_default_profiles()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Restore failed", str(exc))
            return
        self.ctx.notify_profiles_changed()
        self.refresh()
        self.notifyRequested.emit(f"Restored {count} built-in profiles.", "success")
