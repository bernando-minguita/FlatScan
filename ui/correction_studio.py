"""Correction Studio: detection, manual corners, warping, enhancement, quality."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.constants import IMAGE_FILE_FILTER, INTERPOLATION_NAMES, PDF_FILE_FILTER
from app.context import AppContext
from core import dimension_calculator, enhancement, image_loader, perspective
from core.edit_history import EditState, UndoStack
from core.image_loader import ImageLoadError, LoadedImage, load_image_array
from core.pipeline import ProcessingSettings
from database.models import DocumentProfile
from ui.export_window import QuickExportDialog
from ui.icons import make_icon
from ui.image_utils import qimage_to_bgr
from ui.pdf_dialog import PdfImportDialog
from ui.widgets.image_canvas import CANVAS_MIN_AREA, CANVAS_MIN_SIDE, ImageCanvas
from ui.widgets.image_preview import ImagePreview
from ui.widgets.progress_panel import ProgressPanel
from ui.widgets.zoom_controls import ZoomControls
from workers.image_worker import LatestTaskWorker, detect_task, render_task

logger = logging.getLogger(__name__)


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 14)
    layout.setSpacing(9)
    return frame, layout


class SliderRow(QWidget):
    """Label + slider + numeric readout."""

    valueChanged = Signal(int)
    released = Signal(int)

    def __init__(self, label: str, minimum: int, maximum: int, value: int, display=None, parent=None):
        super().__init__(parent)
        self._display = display or (lambda v: str(v))
        # Commits keyboard and click-only changes too, not just mouse releases.
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(500)
        self._commit_timer.timeout.connect(lambda: self.released.emit(self.slider.value()))
        row = QVBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name_label = QLabel(label)
        self.value_label = QLabel(self._display(value))
        self.value_label.setObjectName("Tiny")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.name_label)
        top.addStretch(1)
        top.addWidget(self.value_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        row.addLayout(top)
        row.addWidget(self.slider)

    def _on_change(self, value: int) -> None:
        self.value_label.setText(self._display(value))
        self.valueChanged.emit(value)
        # Mouse drags commit on release; keyboard and groove changes need the
        # debounce so they still create exactly one undo entry.
        if not self.slider.isSliderDown():
            self._commit_timer.start()

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self._commit_timer.stop()
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self.value_label.setText(self._display(int(value)))


class CorrectionStudioPage(QWidget):
    historyChanged = Signal()
    batchFilesRequested = Signal(list)
    notifyRequested = Signal(str, str)
    # Emitted whenever the open document or its saved/dirty state changes, so
    # the main window can enable/disable page-specific menu entries.
    documentStateChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.setAcceptDrops(True)
        self.ctx = ctx
        self.loaded: LoadedImage | None = None
        self.project = None
        self.profile = self._startup_profile()
        self._project_profile_locked = False
        self.undo: UndoStack | None = None
        self.working: EditState | None = None
        self.document: dict | None = None
        self.detection_confidence: float | None = None
        self.detection_message = ""
        self._render_token = 0
        self._detect_token = 0
        self._detected_corners: list | None = None
        self._extra_dirty = False      # profile/dimension changes (not undoable)
        self._saved_snapshot: dict | None = None
        self._saved_at = ""
        self._suspend_controls = False
        self._detection_label = ""

        # Auto-save draft
        self._draft_timer = QTimer(self)
        self._draft_timer.setInterval(30_000)  # 30 seconds
        self._draft_timer.timeout.connect(self._save_draft)
        self._draft_path = Path(self.ctx.config.get("temp_dir")) / "draft_studio.json"
        self._has_unsaved_changes = False

        self._render_worker = LatestTaskWorker(render_task, self)
        self._render_worker.resultReady.connect(self._on_render_result)
        self._render_worker.taskFailed.connect(self._on_render_error)
        self._render_worker.start()
        self._detect_worker = LatestTaskWorker(detect_task, self)
        self._detect_worker.resultReady.connect(self._on_detection_result)
        self._detect_worker.taskFailed.connect(self._on_detect_error)
        self._detect_worker.start()

        self._build_ui()
        self._install_shortcuts()
        self._set_controls_enabled(False)

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Correction Studio")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Detect the document, adjust the four corners, then verify the straightened result."
        )
        subtitle.setObjectName("PageSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        self.open_button = QPushButton("Open image")
        self.open_button.setObjectName("Primary")
        self.open_button.setIcon(make_icon("open", "#FFFFFF", 16))
        self.open_button.clicked.connect(self._choose_file)
        self.pdf_button = QPushButton("From PDF")
        self.pdf_button.setIcon(make_icon("pdf", "#334155", 16))
        self.pdf_button.clicked.connect(self._import_pdf)
        self.paste_button = QPushButton("Paste")
        self.paste_button.setIcon(make_icon("add", "#334155", 16))
        self.paste_button.clicked.connect(self._paste_image)
        header.addWidget(self.pdf_button)
        header.addWidget(self.paste_button)
        header.addWidget(self.open_button)
        root.addLayout(header)

        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        self.file_chip = QLabel("No image loaded")
        self.file_chip.setObjectName("Chip")
        self.size_chip = QLabel("")
        self.size_chip.setObjectName("Chip")
        self.orientation_chip = QLabel("")
        self.orientation_chip.setObjectName("Chip")
        self.format_chip = QLabel("")
        self.format_chip.setObjectName("Chip")
        self.save_chip = QLabel("")
        self.save_chip.setObjectName("Chip")
        for chip in (self.file_chip, self.size_chip, self.orientation_chip, self.format_chip, self.save_chip):
            info_row.addWidget(chip)
        info_row.addStretch(1)
        self.rotation_chip = QLabel("")
        self.rotation_chip.setObjectName("Chip")
        info_row.addWidget(self.rotation_chip)
        root.addLayout(info_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        tools_scroll = QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setMinimumWidth(300)
        tools_scroll.setMaximumWidth(380)
        tools = QWidget()
        tools.setObjectName("Transparent")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(0, 0, 8, 0)
        tools_layout.setSpacing(10)

        # --- document
        document_card, doc_layout = _card()
        doc_layout.addWidget(QLabel("Document profile"))
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Select a document profile with predefined physical dimensions and output settings")
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        doc_layout.addWidget(self.profile_combo)

        dims = QGridLayout()
        dims.setHorizontalSpacing(8)
        dims.setVerticalSpacing(6)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 2000.0)
        self.width_spin.setDecimals(2)
        self.width_spin.setSuffix(" mm")
        self.width_spin.setToolTip("Physical width of the document in millimetres (long edge for landscape)")
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1.0, 2000.0)
        self.height_spin.setDecimals(2)
        self.height_spin.setSuffix(" mm")
        self.height_spin.setToolTip("Physical height of the document in millimetres (short edge for landscape)")
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setSuffix(" DPI")
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setToolTip("Output resolution in dots per inch. Higher DPI = more pixels = larger file")
        dims.addWidget(QLabel("Width"), 0, 0)
        dims.addWidget(self.width_spin, 0, 1)
        dims.addWidget(QLabel("Height"), 1, 0)
        dims.addWidget(self.height_spin, 1, 1)
        dims.addWidget(QLabel("Output DPI"), 2, 0)
        dims.addWidget(self.dpi_spin, 2, 1)
        doc_layout.addLayout(dims)
        for spin in (self.width_spin, self.height_spin, self.dpi_spin):
            spin.valueChanged.connect(self._on_dimensions_changed)

        self.pixel_label = QLabel("—")
        self.pixel_label.setObjectName("Hint")
        doc_layout.addWidget(self.pixel_label)

        rotation_row = QHBoxLayout()
        rotation_row.setSpacing(4)
        self.auto_rotate_button = QPushButton("Auto")
        self.auto_rotate_button.setToolTip("Match the document's expected orientation based on profile dimensions")
        self.rotate_left = QPushButton("90° left")
        self.rotate_left.setToolTip("Rotate the corrected output 90° counter-clockwise")
        self.rotate_right = QPushButton("90° right")
        self.rotate_right.setToolTip("Rotate the corrected output 90° clockwise")
        self.rotate_180 = QPushButton("180°")
        self.rotate_180.setToolTip("Rotate the corrected output 180°")
        self.auto_rotate_button.clicked.connect(lambda: self._set_rotation(0, auto=True))
        self.rotate_left.clicked.connect(lambda: self._rotate_by(-90))
        self.rotate_right.clicked.connect(lambda: self._rotate_by(90))
        self.rotate_180.clicked.connect(lambda: self._rotate_by(180))
        rotation_row.addWidget(self.auto_rotate_button)
        rotation_row.addWidget(self.rotate_left)
        rotation_row.addWidget(self.rotate_right)
        rotation_row.addWidget(self.rotate_180)
        doc_layout.addLayout(rotation_row)

        interpolation_row = QHBoxLayout()
        interpolation_row.setSpacing(6)
        interpolation_label = QLabel("Resampling")
        self.interpolation_combo = QComboBox()
        self.interpolation_combo.addItems(list(INTERPOLATION_NAMES))
        self.interpolation_combo.setToolTip(
            "Interpolation used when straightening the document. Cubic is a good "
            "default; Lanczos keeps the most detail on large scans and Nearest is "
            "fastest but blocky."
        )
        self.interpolation_combo.currentTextChanged.connect(self._on_interpolation_changed)
        interpolation_row.addWidget(interpolation_label)
        interpolation_row.addWidget(self.interpolation_combo, 1)
        doc_layout.addLayout(interpolation_row)
        tools_layout.addWidget(document_card)

        # --- detection
        detect_card, detect_layout = _card()
        detect_layout.addWidget(QLabel("Automatic detection"))
        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setRange(0, 100)
        self.sensitivity_slider.setValue(int(float(self.ctx.config.get("detection_sensitivity", 0.5)) * 100))
        self.sensitivity_slider.setToolTip("Detection sensitivity: lower = stricter (fewer false positives), higher = more permissive (detects difficult cards)")
        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("Sensitivity"))
        self.sensitivity_value = QLabel(f"{self.sensitivity_slider.value()}%")
        self.sensitivity_value.setObjectName("Tiny")
        sensitivity_row.addStretch(1)
        sensitivity_row.addWidget(self.sensitivity_value)
        self.sensitivity_slider.valueChanged.connect(
            lambda value: self.sensitivity_value.setText(f"{value}%")
        )
        detect_layout.addLayout(sensitivity_row)
        detect_layout.addWidget(self.sensitivity_slider)
        self.detect_button = QPushButton("Detect document")
        self.detect_button.setObjectName("Secondary")
        self.detect_button.setToolTip("Run automatic document detection (Ctrl+D)")
        self.detect_button.clicked.connect(lambda: self._start_detection())
        detect_layout.addWidget(self.detect_button)
        
        # Confidence progress bar
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setTextVisible(True)
        self.confidence_bar.setFormat("Confidence: %p%")
        self.confidence_bar.setObjectName("ConfidenceBar")
        self.confidence_bar.setVisible(False)
        detect_layout.addWidget(self.confidence_bar)
        
        self.detection_label = QLabel("Load an image to run detection.")
        self.detection_label.setObjectName("Hint")
        self.detection_label.setWordWrap(True)
        detect_layout.addWidget(self.detection_label)
        tools_layout.addWidget(detect_card)

        # --- enhancement
        enhance_card, enhance_layout = _card()
        enhance_layout.addWidget(QLabel("Enhancement"))
        self.slider_brightness = SliderRow("Brightness", -100, 100, 0)
        self.slider_brightness.setToolTip("Adjust overall image brightness (-100 to +100)")
        self.slider_contrast = SliderRow("Contrast", -100, 100, 0)
        self.slider_contrast.setToolTip("Adjust contrast between light and dark areas (-100 to +100)")
        self.slider_saturation = SliderRow("Saturation", -100, 100, 0)
        self.slider_saturation.setToolTip("Adjust color intensity (-100 = grayscale, +100 = vivid)")
        self.slider_sharpness = SliderRow("Sharpness", 0, 100, 0)
        self.slider_sharpness.setToolTip("Sharpen edges using unsharp masking (0 to 100)")
        self.slider_gamma = SliderRow("Gamma", 30, 300, 100, lambda v: f"{v / 100:.2f}×")
        self.slider_gamma.setToolTip("Gamma correction for mid-tone brightness (0.30 to 3.00)")
        self.slider_denoise = SliderRow("Denoise", 0, 100, 0)
        self.slider_denoise.setToolTip("Reduce noise using non-local means denoising (0 to 100)")
        self.slider_color = SliderRow("Colour boost", 0, 100, 0)
        self.slider_color.setToolTip("Boost color saturation slightly while preserving skin tones (0 to 100)")
        for slider_row in (
            self.slider_brightness,
            self.slider_contrast,
            self.slider_saturation,
            self.slider_sharpness,
            self.slider_gamma,
            self.slider_denoise,
            self.slider_color,
        ):
            enhance_layout.addWidget(slider_row)
        self.slider_map = {
            "brightness": self.slider_brightness,
            "contrast": self.slider_contrast,
            "saturation": self.slider_saturation,
            "sharpness": self.slider_sharpness,
            "gamma": self.slider_gamma,
            "denoise": self.slider_denoise,
            "color_boost": self.slider_color,
        }
        labels = {
            "brightness": "Brightness",
            "contrast": "Contrast",
            "saturation": "Saturation",
            "sharpness": "Sharpness",
            "gamma": "Gamma",
            "denoise": "Denoise",
            "color_boost": "Colour boost",
        }
        for key, slider_row in self.slider_map.items():
            slider_row.valueChanged.connect(lambda value, k=key: self._on_slider_changed(k, value))
            slider_row.released.connect(lambda value, k=key, label=labels[key]: self._commit_slider(k, label))

        toggles = QHBoxLayout()
        self.white_balance_check = QCheckBox("White balance")
        self.white_balance_check.setToolTip("Automatically correct color cast using gray-world assumption")
        self.grayscale_check = QCheckBox("Grayscale")
        self.grayscale_check.setToolTip("Convert output to grayscale (black & white)")
        toggles.addWidget(self.white_balance_check)
        toggles.addWidget(self.grayscale_check)
        toggles.addStretch(1)
        enhance_layout.addLayout(toggles)
        self.white_balance_check.toggled.connect(self._on_toggle_changed)
        self.grayscale_check.toggled.connect(self._on_toggle_changed)

        enhance_buttons = QHBoxLayout()
        self.auto_enhance_button = QPushButton("Auto enhance")
        self.auto_enhance_button.setToolTip("Analyze image and apply automatic enhancement settings")
        self.auto_enhance_button.clicked.connect(self._auto_enhance)
        self.reset_enhance_button = QPushButton("Reset")
        self.reset_enhance_button.setObjectName("Ghost")
        self.reset_enhance_button.setToolTip("Reset all enhancement sliders to defaults")
        self.reset_enhance_button.clicked.connect(self._reset_enhancements)
        enhance_buttons.addWidget(self.auto_enhance_button)
        enhance_buttons.addWidget(self.reset_enhance_button)
        enhance_layout.addLayout(enhance_buttons)
        tools_layout.addWidget(enhance_card)

        # --- quality
        quality_card, quality_layout = _card()
        quality_layout.addWidget(QLabel("Image quality"))
        self.quality_list = QListWidget()
        self.quality_list.setObjectName("QualityList")
        self.quality_list.setMinimumHeight(110)
        quality_layout.addWidget(self.quality_list)
        self.recheck_button = QPushButton("Re-check quality")
        self.recheck_button.setObjectName("Ghost")
        self.recheck_button.clicked.connect(lambda: self._schedule_render(analyze=True))
        quality_layout.addWidget(self.recheck_button)
        tools_layout.addWidget(quality_card)
        tools_layout.addStretch(1)

        tools_scroll.setWidget(tools)
        splitter.addWidget(tools_scroll)

        # --- workspace
        workspace = QWidget()
        workspace.setObjectName("Transparent")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)

        corners_tab = QWidget()
        corners_layout = QVBoxLayout(corners_tab)
        corners_layout.setContentsMargins(10, 10, 10, 10)
        corners_layout.setSpacing(8)
        corners_header = QHBoxLayout()
        corners_hint = QLabel("Drag the four handles. Arrow keys nudge by 1 px, Shift+arrows by 10 px.")
        corners_hint.setObjectName("Hint")
        corners_header.addWidget(corners_hint)
        corners_header.addStretch(1)
        self.zoom_controls = ZoomControls()
        corners_header.addWidget(self.zoom_controls)
        corners_layout.addLayout(corners_header)
        self.canvas = ImageCanvas()
        corners_layout.addWidget(self.canvas, 1)
        reset_row = QHBoxLayout()
        self.reset_corners_button = QPushButton("Reset to detected corners")
        self.reset_corners_button.setIcon(make_icon("refresh", "#334155", 15))
        self.reset_corners_button.clicked.connect(self._reset_corners)
        self.reset_image_button = QPushButton("Reset to original image")
        self.reset_image_button.setObjectName("Ghost")
        self.reset_image_button.clicked.connect(self._reset_to_original)
        reset_row.addWidget(self.reset_corners_button)
        reset_row.addStretch(1)
        reset_row.addWidget(self.reset_image_button)
        corners_layout.addLayout(reset_row)
        self.tabs.addTab(corners_tab, "Corner adjustment")

        result_tab = QWidget()
        result_layout = QVBoxLayout(result_tab)
        result_layout.setContentsMargins(10, 10, 10, 10)
        result_header = QHBoxLayout()
        self.compare_check = QCheckBox("Before / after")
        self.compare_check.toggled.connect(self._on_compare_toggled)
        self.result_size_label = QLabel("")
        self.result_size_label.setObjectName("Hint")
        result_header.addWidget(self.compare_check)
        result_header.addStretch(1)
        result_header.addWidget(self.result_size_label)
        result_layout.addLayout(result_header)
        self.preview = ImagePreview()
        self.preview.set_empty_text("The perspective-corrected document will appear here.")
        result_layout.addWidget(self.preview, 1)
        self.tabs.addTab(result_tab, "Corrected result")

        # --- metadata tab
        metadata_tab = QWidget()
        metadata_layout = QVBoxLayout(metadata_tab)
        metadata_layout.setContentsMargins(10, 10, 10, 10)
        metadata_layout.setSpacing(8)
        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setObjectName("MetadataView")
        self.metadata_text.setPlaceholderText("Load an image to see its metadata.")
        font = self.metadata_text.font()
        font.setFamily("Consolas")
        font.setPixelSize(11)
        self.metadata_text.setFont(font)
        metadata_layout.addWidget(self.metadata_text)
        self.tabs.addTab(metadata_tab, "Metadata")
        workspace_layout.addWidget(self.tabs, 1)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 900])
        root.addWidget(splitter, 1)

        # --- bottom bar
        bottom_card, bottom_layout = _card()
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setIcon(make_icon("undo", "#334155", 15))
        self.undo_button.clicked.connect(self._undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.setIcon(make_icon("redo", "#334155", 15))
        self.redo_button.clicked.connect(self._redo)
        self.quality_chip = QLabel("No image")
        self.quality_chip.setObjectName("Chip")
        self.progress = ProgressPanel()
        bottom_row.addWidget(self.undo_button)
        bottom_row.addWidget(self.redo_button)
        bottom_row.addWidget(self.progress, 1)
        bottom_row.addWidget(self.quality_chip)
        self.save_button = QPushButton("Save project")
        self.save_button.setIcon(make_icon("save", "#334155", 15))
        # clicked emits checked=False; bind it away so notify keeps its default.
        self.save_button.clicked.connect(lambda checked=False: self._save_project(ask_filename=True))
        self.export_button = QPushButton("Export…")
        self.export_button.setObjectName("Primary")
        self.export_button.setIcon(make_icon("export", "#FFFFFF", 15))
        self.export_button.clicked.connect(self._export)
        bottom_row.addWidget(self.save_button)
        bottom_row.addWidget(self.export_button)
        bottom_layout.addLayout(bottom_row)
        root.addWidget(bottom_card)

        self.zoom_controls.zoomInRequested.connect(self.canvas.zoom_in)
        self.zoom_controls.zoomOutRequested.connect(self.canvas.zoom_out)
        self.zoom_controls.fitRequested.connect(self.canvas.fit_to_view)
        self.zoom_controls.actualSizeRequested.connect(self.canvas.actual_size)
        self.canvas.zoomChanged.connect(self.zoom_controls.set_zoom)
        self.canvas.cornersChanged.connect(self._on_corners_changed)
        self.canvas.cornersCommitted.connect(self._on_corners_committed)
        self._refresh_profiles()

    def _install_shortcuts(self) -> None:
        shortcuts = {
            "Ctrl+O": self._choose_file,
            "Ctrl+V": self._paste_image,
            "Ctrl+Z": self._undo,
            "Ctrl+Shift+Z": self._redo,
            "Ctrl+Y": self._redo,
            "Ctrl+S": lambda: self._save_project(ask_filename=True),
            "Ctrl+Shift+S": self._save_project_as,
            "Ctrl+W": self._close_project,
            "Ctrl+E": self._export,
            "Ctrl+D": lambda: self._start_detection(),
        }
        for sequence, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    # -------------------------------------------------------------- profiles
    def _startup_profile(self) -> DocumentProfile:
        """Profile for a new document: the last one used, else the default."""

        recent = str(self.ctx.config.get("recent_profile", "") or "")
        if recent:
            profile = self.ctx.profile_by_name(recent)
            if profile is not None and getattr(profile, "active", True):
                return profile
        return self.ctx.current_profile()

    def _refresh_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = self.ctx.profiles(active_only=True) or self.ctx.profiles()
        current_name = self.profile.name if self.profile else ""
        for profile in profiles:
            self.profile_combo.addItem(profile.name)
        if current_name:
            index = self.profile_combo.findText(current_name)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        if profiles:
            match = next(
                (p for p in profiles if p.name == self.profile_combo.currentText()), None
            )
            if match is None and self.profile is not None and self._project_profile_locked:
                # The profile chosen by load_project is missing/inactive; keep
                # it instead of silently switching to profiles[0], which would
                # render the project with another document's dimensions.
                match = self.profile
                logger.warning(
                    "Project profile '%s' is not available; using it anyway.", match.name
                )
            self.profile = match or profiles[0]
            self._apply_profile_to_controls()

    def _apply_profile_to_controls(self) -> None:
        if not self.profile:
            return
        self._suspend_controls = True
        self.width_spin.setValue(self.profile.width_mm)
        self.height_spin.setValue(self.profile.height_mm)
        self.dpi_spin.setValue(self.profile.dpi)
        self._suspend_controls = False
        self._update_pixel_label()

    def _restore_saved_dimensions(self, record) -> None:
        """Apply the width/height/DPI stored in a project's settings.

        Older project files may omit these keys or hold junk; anything that is
        missing or out of the spin-box range keeps the profile value instead of
        raising or clamping to a wrong size.
        """

        settings = record.settings if isinstance(record.settings, dict) else {}
        self._suspend_controls = True
        try:
            for key, spin in (
                ("width_mm", self.width_spin),
                ("height_mm", self.height_spin),
            ):
                value = settings.get(key)
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if spin.minimum() <= number <= spin.maximum():
                    spin.setValue(number)
            dpi = settings.get("dpi")
            try:
                dpi_value = int(dpi)
            except (TypeError, ValueError):
                dpi_value = None
            if dpi_value is not None and self.dpi_spin.minimum() <= dpi_value <= self.dpi_spin.maximum():
                self.dpi_spin.setValue(dpi_value)
        finally:
            self._suspend_controls = False
        self._update_pixel_label()

    def _on_profile_changed(self, name: str) -> None:
        profile = self.ctx.profile_by_name(name)
        if profile is None:
            return
        self.profile = profile
        self._apply_profile_to_controls()
        if self.loaded is not None:
            self._schedule_render()
            self._mark_dirty()

    def _on_dimensions_changed(self) -> None:
        if self._suspend_controls:
            return
        self._update_pixel_label()
        if self.loaded is not None:
            self._schedule_render()
            self._mark_dirty()

    def _on_interpolation_changed(self, name: str) -> None:
        """Apply a per-document resampling method (persisted with the project)."""

        if self._suspend_controls or self.undo is None or self.working is None:
            return
        if name not in INTERPOLATION_NAMES:
            return
        if self.working.interpolation == name:
            return
        self.working.interpolation = name
        self._push(f"Resampling: {name}")
        self._schedule_render()

    def _update_pixel_label(self) -> None:
        try:
            width, height = dimension_calculator.output_pixel_size(
                self.width_spin.value(), self.height_spin.value(), self.dpi_spin.value(), 0
            )
            rotation = self.working.rotation if self.undo else 0
            if rotation % 180 == 90:
                width, height = height, width
            required = dimension_calculator.mm_to_pixels(self.width_spin.value(), self.dpi_spin.value())
            source_note = ""
            if self.loaded is not None and self.loaded.width < required:
                source_note = f"  ·  source is {self.loaded.width} px wide (below target)"
            self.pixel_label.setText(f"Output: {width} × {height} px{source_note}")
        except dimension_calculator.DimensionError as exc:
            self.pixel_label.setText(str(exc))

    # --------------------------------------------------------------- loading
    def _choose_file(self) -> None:
        folder = str(self.ctx.config.get("project_dir"))
        path, _ = QFileDialog.getOpenFileName(self, "Open document photo", folder, IMAGE_FILE_FILTER)
        if path:
            self.load_image_path(path)

    def load_image_path(self, path: str | Path) -> bool:
        try:
            loaded = image_loader.load_image(path)
        except ImageLoadError as exc:
            QMessageBox.warning(self, "Cannot open image", str(exc))
            return False
        self._begin_new_document(loaded)
        return True

    def load_project(self, record) -> bool:
        source = record.source_path
        if not source or not Path(source).exists():
            QMessageBox.warning(
                self,
                "Original image missing",
                "The image referenced by this project could not be found:\n"
                f"{source or '(no path)'}\n\n"
                "Use Processing History → Relink source to choose the moved file.",
            )
            return False
        try:
            loaded = image_loader.load_image(source)
        except ImageLoadError as exc:
            QMessageBox.warning(self, "Cannot open project image", str(exc))
            return False

        self.loaded = loaded
        self.project = record
        profile = self.ctx.repository.get_profile(record.profile_id)
        if profile is None and record.profile_name:
            profile = self.ctx.profile_by_name(record.profile_name)
        self.profile = profile or self.ctx.current_profile()
        self._project_profile_locked = True
        self._refresh_profiles()
        self._project_profile_locked = False
        self._apply_profile_to_controls()
        # Restore the measurements the project was saved with. They may differ
        # from the profile (the user can override width/height/DPI in the
        # studio), and re-applying the profile above just overwrote them.
        self._restore_saved_dimensions(record)
        self.detection_confidence = None
        self.detection_message = "Loaded saved project."

        state = self.ctx.projects.rebuild_state(record, (loaded.width, loaded.height))
        self.undo = self.ctx.projects.restore_undo(record, state)
        self.working = self.undo.current.clone()
        try:
            corners = self.working.quad()
        except perspective.InvalidQuadrilateral:
            corners = None  # corrupt saved data: fall back to the canvas default
        self.canvas.set_image(loaded.image, corners)
        self._sync_controls_from_state()
        self._set_file_info(loaded, record.name)
        self._set_controls_enabled(True)
        self.detection_label.setText("Loaded saved corners from the project.")
        # A freshly loaded project matches its stored record: not dirty.
        self._detected_corners = None
        self._saved_snapshot = self.working.to_dict() if self.working is not None else None
        self._extra_dirty = False
        self._saved_at = (record.updated_at or "")[11:16] if record.updated_at else ""
        self._update_save_state()
        self._update_metadata(loaded)
        self._schedule_render()
        return True

    def _begin_new_document(self, loaded: LoadedImage) -> None:
        self.loaded = loaded
        self.project = None
        self.document = None
        self.detection_confidence = None
        self._set_file_info(loaded, "")
        self.profile = self._startup_profile()
        self._refresh_profiles()
        self._apply_profile_to_controls()

        settings = enhancement.auto_enhance_params(loaded.image) if self.ctx.config.get("auto_enhance") else None
        state = EditState(
            corners=[[0, 0], [loaded.width - 1, 0], [loaded.width - 1, loaded.height - 1], [0, loaded.height - 1]],
            rotation=0,
            auto_orientation=True,
            enhancement=settings or dict(enhancement.DEFAULT_PARAMS),
            interpolation=str(self.ctx.config.get("interpolation", "Cubic")),
        )
        self.working = state.clone()
        self.undo = UndoStack(state)
        self.canvas.set_image(loaded.image, None)
        self._sync_controls_from_state()
        self._set_controls_enabled(True)
        self.preview.clear()
        self.preview.set_before(None)
        self.quality_list.clear()
        self.tabs.setCurrentIndex(0)
        self._detected_corners = None
        self._saved_snapshot = None
        self._extra_dirty = False
        self._saved_at = ""
        self._update_save_state()
        self._draft_timer.start()
        self._update_metadata(loaded)
        self._start_detection()

    def _set_file_info(self, loaded: LoadedImage, project_name: str) -> None:
        name = loaded.display_name if not project_name else f"{project_name} · {loaded.display_name}"
        self.file_chip.setText(name)
        self.size_chip.setText(f"{loaded.width} × {loaded.height} px")
        self.orientation_chip.setText(loaded.orientation)
        parts = []
        if loaded.file_size:
            parts.append(loaded.file_size_label)
        if loaded.exif_rotated:
            parts.append("EXIF rotation applied")
        if loaded.path:
            parts.append(loaded.path.suffix.upper().lstrip("."))
        self.format_chip.setText("  ·  ".join(parts) or "Clipboard")

    def _update_metadata(self, loaded: LoadedImage) -> None:
        """Extract and display image metadata (EXIF)."""
        if not hasattr(self, 'metadata_text'):
            return
        if loaded.path is None:
            self.metadata_text.setPlainText("No metadata available (clipboard/imported image).")
            return
        try:
            from PIL import Image
            with Image.open(loaded.path) as img:
                exif = img.getexif()
                if not exif:
                    self.metadata_text.setPlainText("No EXIF metadata found in this image.")
                    return
                
                # EXIF tag names (common ones)
                exif_tags = {
                    271: "Make",
                    272: "Model",
                    282: "X Resolution",
                    283: "Y Resolution",
                    296: "Resolution Unit",
                    305: "Software",
                    306: "DateTime",
                    33434: "Exposure Time",
                    33437: "F Number",
                    34855: "ISO Speed Ratings",
                    36867: "DateTime Original",
                    36868: "DateTime Digitized",
                    37500: "Maker Note",
                    37510: "User Comment",
                    40960: "Exif Version",
                    40961: "FlashPix Version",
                    41985: "Color Space",
                    41986: "Pixel X Dimension",
                    41987: "Pixel Y Dimension",
                    41988: "Related Sound File",
                    41989: "Interoperability Offset",
                    41990: "Flash Energy",
                    41991: "Spatial Frequency Response",
                    41992: "Focal Plane X Resolution",
                    41993: "Focal Plane Y Resolution",
                    41994: "Focal Plane Resolution Unit",
                    41995: "Subject Location",
                    41996: "Exposure Index",
                    41997: "Sensing Method",
                    41998: "File Source",
                    41999: "Scene Type",
                    42000: "CFAPattern",
                    42001: "Custom Rendered",
                    42002: "Exposure Mode",
                    42003: "White Balance",
                    42004: "Digital Zoom Ratio",
                    42005: "Focal Length in 35mm Film",
                    42006: "Scene Capture Type",
                    42007: "Gain Control",
                    42008: "Contrast",
                    42009: "Saturation",
                    42010: "Sharpness",
                    42011: "Device Setting Description",
                    42012: "Subject Distance Range",
                    42013: "Image Unique ID",
                }
                
                lines = []
                lines.append(f"File: {loaded.path.name}")
                lines.append(f"Format: {img.format}")
                lines.append(f"Mode: {img.mode}")
                lines.append(f"Size: {img.width} × {img.height} px")
                lines.append("")
                lines.append("EXIF Metadata:")
                lines.append("-" * 40)
                
                for tag_id, value in exif.items():
                    tag_name = exif_tags.get(tag_id, f"Tag {tag_id}")
                    # Format value nicely
                    if isinstance(value, bytes):
                        try:
                            value = value.decode('utf-8', errors='ignore')
                        except Exception:
                            value = str(value)
                    elif isinstance(value, tuple):
                        value = ", ".join(str(v) for v in value)
                    lines.append(f"  {tag_name}: {value}")
                
                if len(lines) <= 6:  # Only header lines
                    lines.append("  (no recognized EXIF tags)")
                
                self.metadata_text.setPlainText("\n".join(lines))
        except Exception as exc:
            self.metadata_text.setPlainText(f"Failed to read metadata: {exc}")

    def _editable_focus(self) -> QWidget | None:
        """Return the focused text widget, if the shortcut belongs to it.

        ``Ctrl+V`` must paste into a dimension spinbox instead of replacing the
        open document, so the image-paste handler defers to focused text fields.
        """

        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QAbstractSpinBox, QTextEdit)):
            return widget
        return None

    def _paste_image(self) -> None:
        target = self._editable_focus()
        if target is not None:
            if isinstance(target, QAbstractSpinBox):
                editor = target.lineEdit()
                if editor is not None:
                    editor.paste()
            else:
                target.paste()
            return
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasImage():
            qimage = clipboard.image()
            try:
                image = qimage_to_bgr(qimage)
            except ValueError as exc:
                QMessageBox.warning(self, "Clipboard", str(exc))
                return
            self._begin_new_document(load_image_array(image, "Clipboard image"))
            return
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in image_loader.SUPPORTED_IMAGE_EXTENSIONS:
                    self.load_image_path(path)
                    return
        QMessageBox.information(
            self, "Nothing to paste", "The clipboard does not contain an image."
        )

    def _import_pdf(self) -> None:
        folder = str(self.ctx.config.get("project_dir"))
        path, _ = QFileDialog.getOpenFileName(self, "Import PDF pages", folder, PDF_FILE_FILTER)
        if not path:
            return
        dialog = PdfImportDialog(path, self.ctx.config.resolve_dir("temp_dir"), self)
        if dialog.exec() != PdfImportDialog.DialogCode.Accepted:
            return
        paths = dialog.imported_paths()
        if not paths:
            return
        self.load_image_path(paths[0])
        if len(paths) > 1:
            self.batchFilesRequested.emit([str(p) for p in paths[1:]])
            self.notifyRequested.emit(
                f"{len(paths) - 1} more PDF pages were added to Batch Processing.", "info"
            )

    # ------------------------------------------------------------- detection
    def _reset_corners(self) -> None:
        """Restore the last successful detection (running one if needed)."""
        if self.loaded is None or self.undo is None:
            return
        if self._detected_corners is None:
            self._start_detection()
            return
        try:
            self.working.set_corners(self._detected_corners)
        except perspective.InvalidQuadrilateral:
            self._detected_corners = None
            self._start_detection()
            return
        self.canvas.set_corners(self.working.corners, quiet=True)
        self._push("Reset to detected corners")
        self._schedule_render()

    def _start_detection(self) -> None:
        if self.loaded is None:
            return
        self._detect_token += 1
        token = self._detect_token
        self.progress.set_busy("Detecting the document…")
        self.detect_button.setEnabled(False)
        self.detection_label.setText("Analysing edges and contours…")
        self.confidence_bar.setVisible(False)
        self._detect_worker.submit(
            token,
            {
                "image": self.loaded.image,
                "sensitivity": self.sensitivity_slider.value() / 100.0,
            },
        )

    def _on_detection_result(self, token: int, result: dict) -> None:
        if token != self._detect_token or self.loaded is None or self.undo is None:
            return
        self.detect_button.setEnabled(True)
        corners = result.get("quad") or self.working.corners
        if result.get("success"):
            # Remember the detection so "Reset to detected corners" can
            # restore it instantly instead of re-running the analysis.
            self._detected_corners = [list(map(float, point)) for point in corners]
        self.working.set_corners(corners)
        if result.get("success"):
            self._push("Auto-detect corners")
        self.detection_confidence = float(result.get("confidence", 0.0))
        self.detection_message = result.get("message", "")
        self.detection_label.setText(self.detection_message)
        
        # Update confidence progress bar
        confidence_pct = int(round(self.detection_confidence * 100))
        self.confidence_bar.setValue(confidence_pct)
        self.confidence_bar.setVisible(True)
        # Color-code based on confidence
        if confidence_pct >= 70:
            self.confidence_bar.setStyleSheet("QProgressBar::chunk { background-color: #15803D; }")
        elif confidence_pct >= 45:
            self.confidence_bar.setStyleSheet("QProgressBar::chunk { background-color: #B45309; }")
        else:
            self.confidence_bar.setStyleSheet("QProgressBar::chunk { background-color: #B91C1C; }")
        
        self.canvas.set_corners(self.working.corners, quiet=True)
        self._schedule_render()
        if not result.get("success"):
            self.notifyRequested.emit(
                "Automatic detection was uncertain — please check the corners.", "warning"
            )

    def _on_detect_error(self, token: int, message: str) -> None:
        if token != self._detect_token:
            return
        self.detect_button.setEnabled(True)
        self.progress.set_idle("Detection failed")
        self.detection_label.setText(message)
        QMessageBox.warning(
            self,
            "Detection failed",
            f"The document could not be detected automatically.\n\n{message}\n\n"
            "Adjust the corners manually in the Corner adjustment tab.",
        )

    def _on_corners_changed(self, corners) -> None:
        if self.undo is None or self._suspend_controls:
            return
        self.working.corners = [list(point) for point in corners]

    def _on_corners_committed(self, corners) -> None:
        if self.undo is None:
            return
        self.working.corners = [list(point) for point in corners]
        try:
            if not perspective.is_valid_quad(
                self.working.quad(), min_area=CANVAS_MIN_AREA, min_side=CANVAS_MIN_SIDE
            ):
                return
        except perspective.InvalidQuadrilateral:
            return
        self._push("Corner adjustment")
        self._schedule_render()

    def _set_rotation(self, degrees: int, auto: bool = False) -> None:
        if self.undo is None:
            return
        self.working.rotation = degrees % 360
        self.working.auto_orientation = auto
        self._push("Auto orientation" if auto else f"Rotate {degrees % 360}°")
        self._update_pixel_label()
        self._schedule_render()

    def _rotate_by(self, degrees: int) -> None:
        if self.undo is None:
            return
        current = self.working.rotation
        self._set_rotation(current + degrees, auto=False)

    # ------------------------------------------------------------ rendering
    def _settings(self) -> ProcessingSettings:
        state = self.working if self.undo else None
        return ProcessingSettings(
            width_mm=self.width_spin.value(),
            height_mm=self.height_spin.value(),
            dpi=self.dpi_spin.value(),
            rotation=state.rotation if state else 0,
            auto_orientation=state.auto_orientation if state else True,
            interpolation=state.interpolation if state else "Cubic",
            enhancement=dict(state.enhancement) if state else {},
        )

    def _schedule_render(self, analyze: bool = True) -> None:
        if self.loaded is None or self.undo is None:
            return
        try:
            dimension_calculator.validate_dimensions(
                self.width_spin.value(), self.height_spin.value(), self.dpi_spin.value()
            )
        except dimension_calculator.DimensionError as exc:
            self.progress.set_idle("Invalid dimensions", str(exc))
            return
        self._render_token += 1
        token = self._render_token
        self.progress.set_busy("Rendering corrected preview…")
        self._render_worker.submit(
            token,
            {
                "image": self.loaded.image,
                "corners": self.working.corners,
                "settings": self._settings(),
                "confidence": self.detection_confidence,
                "analyze": analyze,
            },
        )

    def _on_render_result(self, token: int, result: dict) -> None:
        if token != self._render_token:
            return
        self.document = result
        image = result["image"]
        self.preview.set_before(result.get("base"))
        self.preview.set_image(image)
        self.preview.set_compare(self.compare_check.isChecked())
        width, height = result["size"]
        rotation = result.get("rotation", 0)
        self.result_size_label.setText(
            f"{width} × {height} px  ·  rotation {rotation}°  ·  {self.dpi_spin.value()} DPI"
        )
        self.rotation_chip.setText(f"Rotation {rotation}°")
        self._update_pixel_label()
        self._fill_quality(result.get("quality") or {}, result.get("confidence"))
        self.progress.set_idle(f"Ready · {width} × {height} px")
        self._update_undo_buttons()

    def _on_render_error(self, token: int, message: str) -> None:
        if token != self._render_token:
            return
        self.progress.set_idle("Correction failed", message)
        self.notifyRequested.emit(f"Perspective correction failed: {message}", "error")

    def _fill_quality(self, quality: dict, confidence) -> None:
        issues = quality.get("issues") or []
        self.quality_list.clear()
        worst = "info"
        order = {"info": 0, "warning": 1, "critical": 2}
        for issue in issues:
            severity = issue.get("severity", "info")
            worst = severity if order.get(severity, 0) > order.get(worst, 0) else worst
            color = {"critical": "#B91C1C", "warning": "#B45309", "info": "#15803D"}.get(severity, "#334155")
            item = QListWidgetItem(issue.get("title", ""))
            item.setToolTip(issue.get("message", ""))
            item.setForeground(QColor(color))
            icon_name = "check" if severity == "info" else "warning"
            item.setIcon(make_icon(icon_name, color, 14))
            self.quality_list.addItem(item)
        if not issues:
            self.quality_list.addItem(QListWidgetItem("Quality analysis was skipped."))
        if confidence is not None:
            item = QListWidgetItem(f"Detection confidence: {confidence:.0%}")
            item.setForeground(QColor("#64748B"))
            self.quality_list.addItem(item)

        if worst == "critical":
            self.quality_chip.setText("Quality needs attention")
            self.quality_chip.setObjectName("ChipDanger")
        elif worst == "warning":
            self.quality_chip.setText("Quality warnings")
            self.quality_chip.setObjectName("ChipWarning")
        else:
            self.quality_chip.setText("Quality OK")
            self.quality_chip.setObjectName("ChipSuccess")
        self.quality_chip.style().unpolish(self.quality_chip)
        self.quality_chip.style().polish(self.quality_chip)

    # ------------------------------------------------------- state <-> UI
    def _sync_controls_from_state(self) -> None:
        if self.undo is None or self.working is None:
            return
        state = self.working
        self._suspend_controls = True
        self.slider_brightness.set_value(int(state.enhancement.get("brightness", 0)))
        self.slider_contrast.set_value(int(state.enhancement.get("contrast", 0)))
        self.slider_saturation.set_value(int(state.enhancement.get("saturation", 0)))
        self.slider_sharpness.set_value(int(state.enhancement.get("sharpness", 0)))
        self.slider_gamma.set_value(int(float(state.enhancement.get("gamma", 1.0)) * 100))
        self.slider_denoise.set_value(int(state.enhancement.get("denoise", 0)))
        self.slider_color.set_value(int(state.enhancement.get("color_boost", 0)))
        self.white_balance_check.setChecked(bool(state.enhancement.get("white_balance")))
        self.grayscale_check.setChecked(bool(state.enhancement.get("grayscale")))
        index = self.interpolation_combo.findText(state.interpolation)
        if index >= 0:
            self.interpolation_combo.setCurrentIndex(index)
        self._suspend_controls = False
        self._update_pixel_label()
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        if self.undo is None:
            self.undo_button.setEnabled(False)
            self.redo_button.setEnabled(False)
            return
        self.undo_button.setEnabled(self.undo.can_undo)
        self.redo_button.setEnabled(self.undo.can_redo)
        self.undo_button.setToolTip(f"Undo {self.undo.undo_label}" if self.undo.can_undo else "Nothing to undo")
        self.redo_button.setToolTip(f"Redo {self.undo.redo_label}" if self.undo.can_redo else "Nothing to redo")

    def _on_slider_changed(self, key: str, value: int) -> None:
        if self.undo is None or self._suspend_controls:
            return
        actual = value / 100.0 if key == "gamma" else float(value)
        self.working.enhancement[key] = actual
        self._schedule_render()

    def _commit_slider(self, key: str, label: str) -> None:
        if self.undo is None:
            return
        actual = self.slider_map[key].value() / 100.0 if key == "gamma" else float(self.slider_map[key].value())
        self.working.enhancement[key] = actual
        self._push(label)
        self._update_undo_buttons()

    def _on_toggle_changed(self) -> None:
        if self.undo is None or self._suspend_controls:
            return
        self.working.enhancement["white_balance"] = self.white_balance_check.isChecked()
        self.working.enhancement["grayscale"] = self.grayscale_check.isChecked()
        self._push("Enhancement toggle")
        self._schedule_render()

    def _auto_enhance(self) -> None:
        if self.undo is None or self.loaded is None:
            return
        params = enhancement.auto_enhance_params(self.loaded.image)
        self.working.enhancement = params
        self._push("Auto enhance")
        self._sync_controls_from_state()
        self._schedule_render()
        self.notifyRequested.emit("Automatic enhancement applied.", "success")

    def _reset_enhancements(self) -> None:
        if self.undo is None:
            return
        self.working.enhancement = dict(enhancement.DEFAULT_PARAMS)
        self._push("Reset enhancement")
        self._sync_controls_from_state()
        self._schedule_render()

    def _push(self, label: str) -> None:
        if self.undo is not None and self.working is not None:
            self.undo.push(label, self.working)
            self._has_unsaved_changes = True
            self._update_save_state()

    # -------------------------------------------------------- save-state UI
    def _mark_dirty(self) -> None:
        """Flag a non-undoable change (profile / output dimensions)."""
        self._extra_dirty = True
        self._has_unsaved_changes = True
        # _update_save_state() already emits documentStateChanged.
        self._update_save_state()

    def _is_dirty(self) -> bool:
        """True when the working state differs from the last saved snapshot."""
        if self._extra_dirty:
            return True
        if self.working is None:
            return False
        current = self.working.to_dict()
        if self._saved_snapshot is not None:
            return current != self._saved_snapshot
        # Never saved: compare against the initial undo-stack state.
        if self.undo is None:
            return False
        states = self.undo.to_dict().get("states") or []
        return not states or current != states[0]

    def _update_save_state(self) -> None:
        """Refresh the persistent Saved / Unsaved-changes chip."""
        if self.loaded is None:
            self.save_chip.setText("")
            self.documentStateChanged.emit()
            return
        if self._is_dirty():
            self.save_chip.setText("Unsaved changes *")
        elif self._saved_snapshot is None:
            self.save_chip.setText("Not saved")
        else:
            self.save_chip.setText(f"Saved {self._saved_at}" if self._saved_at else "Saved")
        self.documentStateChanged.emit()

    def _apply_state(self, state: EditState) -> None:
        self.working = state.clone()
        self._suspend_controls = True
        self.canvas.set_corners(self.working.corners, quiet=True)
        self._suspend_controls = False
        self._sync_controls_from_state()
        self._schedule_render()
        self._update_save_state()

    def _undo(self) -> None:
        if self.undo is None:
            return
        state = self.undo.undo()
        if state is not None:
            self._apply_state(state)
            self._update_undo_buttons()
            self.notifyRequested.emit(f"Undone: {self.undo.redo_label or 'change'}", "info")

    def _redo(self) -> None:
        if self.undo is None:
            return
        state = self.undo.redo()
        if state is not None:
            self._apply_state(state)
            self._update_undo_buttons()
            self.notifyRequested.emit("Change reapplied.", "info")

    def _reset_to_original(self) -> None:
        if self.loaded is None:
            return
        answer = QMessageBox.question(
            self,
            "Reset to the original image",
            "All corner and enhancement changes for this session will be discarded. "
            "The source file on disk is never modified. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.loaded.path and Path(self.loaded.path).exists():
            self.load_image_path(self.loaded.path)
        else:
            self._begin_new_document(load_image_array(self.loaded.image, self.loaded.source_label))
        self.notifyRequested.emit("Editor reset to the original image.", "info")

    def _on_compare_toggled(self, enabled: bool) -> None:
        self.preview.set_compare(enabled)

    # --------------------------------------------------------------- actions
    def _save_project(self, notify: bool = True, ask_filename: bool = False) -> bool:
        """Persist the current document to history. Returns True on success.

        When ``ask_filename`` is true and this is a first save (no user-chosen
        project file yet), a file dialog prompts the user for a ``.json`` path.
        """
        if self.loaded is None or self.undo is None:
            return False

        chosen_path: str | None = None
        if ask_filename and (self.project is None or not self.project.project_file_path):
            suggested_name = Path(self.loaded.display_name).stem if self.loaded else "Untitled"
            suggested_dir = Path(self.ctx.config.get("project_dir"))
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save project",
                str(suggested_dir / f"{suggested_name}.json"),
                "FlatScan project (*.json);;All files (*.*)",
            )
            if not path:
                return False
            chosen_path = path
        elif self.project is not None and self.project.project_file_path:
            chosen_path = self.project.project_file_path
        document = self.document or {}
        image = document.get("image")
        name = self.project.name if self.project else Path(self.loaded.display_name).stem
        try:
            self.project = self.ctx.projects.build_record(
                record=self.project,
                state=self.working,
                profile=self.profile,
                source_path=str(self.loaded.path) if self.loaded.path else "",
                preview_image=image,
                project_name=name,
                status="success",
                undo=self.undo,
                source_image=self.loaded.image,
                # Manual overrides in the studio must survive a save; without
                # these the profile measurements silently replaced them.
                dpi=self.dpi_spin.value(),
                width_mm=self.width_spin.value(),
                height_mm=self.height_spin.value(),
                project_file_path=chosen_path or "",
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, "Could not save the project", str(exc))
            return False
        try:
            if self.loaded.path:
                self.ctx.config.set("recent_profile", self.profile.name)
        except Exception as exc:  # noqa: BLE001 - preferences must not abort the save
            logger.warning("Could not persist the recent profile: %s", exc)
        # The database write succeeded, but the portable JSON sidecar can fail
        # independently (disk full, permission error) — tell the user.
        project_file = Path(self.project.project_file_path) if self.project.project_file_path else self.ctx.projects.project_file(self.project.id)
        partial = not project_file.exists()
        self.file_chip.setText(f"{name} · {self.loaded.display_name}")
        if partial:
            self._update_save_state()
            self.notifyRequested.emit(
                "Saved to history, but the portable project file could not be written.",
                "warning",
            )
            return False
        self._saved_snapshot = self.working.to_dict() if self.working is not None else None
        self._extra_dirty = False
        self._has_unsaved_changes = False
        self._saved_at = datetime.now().strftime("%H:%M")
        self._update_save_state()
        self._clear_draft()
        self.historyChanged.emit()
        if notify:
            self.notifyRequested.emit(
                f"Project saved to {Path(self.project.thumbnail_path or project_file).name}",
                "success",
            )
        return True

    def _save_project_as(self) -> None:
        """Save the project, then write a copy to a chosen ``.json`` path."""

        if self.loaded is None or self.undo is None:
            return
        if not self._save_project(notify=False, ask_filename=False):
            return
        suggested = self.ctx.projects.project_file(self.project.id)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save a copy of the project",
            str(suggested),
            "FlatScan project (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            written = self.ctx.projects.save_as(self.project, path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save the copy", str(exc))
            return
        self.notifyRequested.emit(f"Project copy saved to {written.name}.", "success")

    def _close_project(self) -> None:
        """Discard the open document and return the studio to its empty state."""

        if self.loaded is None:
            return
        if not self._confirm_discard("Close project"):
            return
        self._clear_document()
        self.notifyRequested.emit("Project closed.", "info")

    def _revert_project(self) -> None:
        """Reload the last saved state of the open project."""

        if self.loaded is None:
            return
        if self.project is None:
            self.notifyRequested.emit(
                "This document has not been saved yet, so there is nothing to revert to.",
                "warning",
            )
            return
        if not self._confirm_discard("Revert to the saved version"):
            return
        record = self.ctx.repository.get_project(self.project.id)
        if record is None:
            QMessageBox.warning(
                self,
                "Project not found",
                "This project is no longer in the history, so it cannot be reverted.",
            )
            return
        if self.load_project(record):
            self.notifyRequested.emit("Reverted to the last saved version.", "success")

    def _confirm_discard(self, action: str) -> bool:
        """Ask before throwing away unsaved edits; True means "go ahead"."""

        if not self._is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            f"{action}?",
            "This document has unsaved changes. They will be lost.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def has_unsaved_changes(self) -> bool:
        """Public hook used by the main window's close guard."""

        return self.loaded is not None and self._is_dirty()

    def _clear_document(self) -> None:
        """Reset every widget and buffer to the "no document" state."""

        self._draft_timer.stop()
        self._clear_draft()
        self.loaded = None
        self.project = None
        self.document = None
        self.undo = None
        self.working = None
        self._detected_corners = None
        self._saved_snapshot = None
        self._extra_dirty = False
        self._has_unsaved_changes = False
        self._saved_at = ""
        self.detection_confidence = None
        self.detection_message = ""
        self.canvas.clear_image()
        self.preview.clear()
        self.preview.set_before(None)
        self.quality_list.clear()
        self.quality_chip.setText("No image")
        self.quality_chip.setObjectName("Chip")
        self.quality_chip.style().unpolish(self.quality_chip)
        self.quality_chip.style().polish(self.quality_chip)
        self.file_chip.setText("No image loaded")
        self.size_chip.setText("")
        self.orientation_chip.setText("")
        self.format_chip.setText("")
        self.rotation_chip.setText("")
        self.confidence_bar.setVisible(False)
        self.confidence_bar.setValue(0)
        self.detection_label.setText("Load an image to run detection.")
        self.result_size_label.setText("")
        self.pixel_label.setText("—")
        self.metadata_text.setPlainText("Load an image to see its metadata.")
        self.tabs.setCurrentIndex(0)
        self.progress.set_idle("Ready")
        self._set_controls_enabled(False)
        self._update_save_state()
        self._update_undo_buttons()

    def _export(self) -> None:
        if self.document is None or self.loaded is None:
            QMessageBox.information(
                self, "Nothing to export", "Load an image and finish the correction first."
            )
            return
        dialog = QuickExportDialog(
            self.ctx,
            self.document["image"],
            Path(self.loaded.display_name).stem,
            self.profile,
            parent=self,
        )
        if dialog.exec() != QuickExportDialog.DialogCode.Accepted:
            return
        paths = dialog.exported_paths()
        if not paths:
            return
        self._save_project(notify=False, ask_filename=False)
        if self.project is not None:
            self.project.output_path = str(paths[0])
            self.ctx.projects.mark_exported(self.project)
        self.historyChanged.emit()
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Export complete")
        msg.setText(f"Exported '{paths[0].name}'")
        msg.setInformativeText(f"The corrected document has been written to:\n{paths[0]}")
        open_button = msg.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Ok)
        msg.setDefaultButton(QMessageBox.StandardButton.Ok)
        msg.exec()
        if msg.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0].parent)))
    # -------------------------------------------------------------- enablement
    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.profile_combo,
            self.width_spin,
            self.height_spin,
            self.dpi_spin,
            self.auto_rotate_button,
            self.rotate_left,
            self.rotate_right,
            self.rotate_180,
            self.interpolation_combo,
            self.detect_button,
            self.undo_button,
            self.redo_button,
            self.save_button,
            self.export_button,
            self.reset_corners_button,
            self.reset_image_button,
            self.compare_check,
            self.auto_enhance_button,
            self.reset_enhance_button,
            self.recheck_button,
            self.paste_button,
            self.pdf_button,
        ):
            widget.setEnabled(enabled)
        for slider_row in self.slider_map.values():
            slider_row.setEnabled(enabled)
        self.white_balance_check.setEnabled(enabled)
        self.grayscale_check.setEnabled(enabled)
        self.sensitivity_slider.setEnabled(True)

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                suffix = Path(url.toLocalFile()).suffix.lower()
                if suffix in image_loader.SUPPORTED_IMAGE_EXTENSIONS or suffix == ".pdf":
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        image_paths: list[Path] = []
        pdf_path: Path | None = None
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".pdf" and pdf_path is None:
                pdf_path = path
            elif path.suffix.lower() in image_loader.SUPPORTED_IMAGE_EXTENSIONS:
                image_paths.append(path)
        if image_paths:
            self.load_image_path(image_paths[0])
            if len(image_paths) > 1:
                self.batchFilesRequested.emit([str(p) for p in image_paths[1:]])
                self.notifyRequested.emit(
                    f"{len(image_paths) - 1} additional images were added to Batch Processing.",
                    "info",
                )
            event.acceptProposedAction()
        elif pdf_path is not None:
            self._open_pdf_path(pdf_path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _open_pdf_path(self, path: Path) -> None:
        dialog = PdfImportDialog(path, self.ctx.config.resolve_dir("temp_dir"), self)
        if dialog.exec() == PdfImportDialog.DialogCode.Accepted and dialog.imported_paths():
            paths = dialog.imported_paths()
            self.load_image_path(paths[0])
            if len(paths) > 1:
                self.batchFilesRequested.emit([str(p) for p in paths[1:]])

    # ------------------------------------------------------------------ draft auto-save
    def _save_draft(self) -> None:
        """Save current studio state as a draft for crash recovery."""
        if self.loaded is None or self.working is None or self.undo is None:
            return
        if not self._has_unsaved_changes:
            return
        try:
            draft_data = {
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "source_path": str(self.loaded.path) if self.loaded.path else "",
                "source_name": self.loaded.display_name,
                "source_size": [self.loaded.width, self.loaded.height],
                "profile_name": self.profile.name if self.profile else "",
                "working_state": self.working.to_dict(),
                "undo_history": self.undo.to_dict(),
                "width_mm": self.width_spin.value(),
                "height_mm": self.height_spin.value(),
                "dpi": self.dpi_spin.value(),
                "sensitivity": self.sensitivity_slider.value() / 100.0,
            }
            self._draft_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._draft_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(draft_data, indent=2), encoding="utf-8")
            tmp_path.replace(self._draft_path)
            logger.debug("Draft saved to %s", self._draft_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save draft: %s", exc)

    def _load_draft(self) -> bool:
        """Load draft if it exists and matches current source. Returns True if loaded."""
        if not self._draft_path.exists():
            return False
        try:
            data = json.loads(self._draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read draft: %s", exc)
            return False

        # Validate draft
        if data.get("version") != 1:
            return False
        if not data.get("source_path") or not Path(data["source_path"]).exists():
            return False

        # Check if source matches (by path and size)
        source_path = Path(data["source_path"])
        source_size = data.get("source_size", [0, 0])
        if self.loaded and (self.loaded.path != source_path or 
                            [self.loaded.width, self.loaded.height] != source_size):
            return False

        # Restore state
        try:
            self.working = EditState.from_dict(data["working_state"])
            self.undo = UndoStack.from_dict(data["undo_history"])
            self.profile = self.ctx.profile_by_name(data.get("profile_name", "")) or self.ctx.current_profile()
            self._refresh_profiles()
            self._apply_profile_to_controls()

            # Restore UI values
            self.width_spin.setValue(data.get("width_mm", self.profile.width_mm))
            self.height_spin.setValue(data.get("height_mm", self.profile.height_mm))
            self.dpi_spin.setValue(data.get("dpi", self.profile.dpi))
            self.sensitivity_slider.setValue(int(data.get("sensitivity", 0.5) * 100))

            self._sync_controls_from_state()
            self._has_unsaved_changes = True
            self._update_save_state()
            logger.info("Draft restored from %s", self._draft_path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to restore draft: %s", exc)
            return False

    def _clear_draft(self) -> None:
        """Remove the draft file."""
        try:
            if self._draft_path.exists():
                self._draft_path.unlink()
        except OSError:
            pass

    def check_and_recover_draft(self) -> None:
        """Check for a saved draft and offer to recover it."""
        if self._load_draft():
            self.notifyRequested.emit("Draft recovered from previous session.", "success")
            self._schedule_render()
        else:
            # No draft or draft invalid - clear any stale draft
            self._clear_draft()

    def shutdown(self) -> None:
        for worker in (self._render_worker, self._detect_worker):
            worker.stop()
        for worker in (self._render_worker, self._detect_worker):
            # Wait without a short timeout: destroying a running QThread while
            # a large render is in flight would abort the process on close.
            worker.wait()
