"""Batch processing of many images plus front/back pairing."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.config import AppConfig
from app.constants import (
    OVERWRITE_RENAME,
    RASTER_FORMATS,
    STATUS_FAILED,
    STATUS_REVIEW,
    STATUS_SUCCESS,
)
from core import corner_detection, enhancement, image_detector, pipeline
from core.image_exporter import (
    ExportError,
    FORMAT_EXTENSIONS,
    resolve_target,
    same_path,
    save_raster,
    unique_path,
)
from core.image_loader import ImageLoadError, is_supported, list_images_in_folder, load_image
from core.pdf_handler import build_pdf
from database.models import DocumentProfile
from .export_service import build_filename, sanitize_filename

logger = logging.getLogger(__name__)

FRONT_WORDS = {"front", "f", "face", "obverse", "amam", "amami", "1"}
BACK_WORDS = {"back", "b", "rear", "reverse", "khalf", "khalfi", "2"}
_SPLIT = re.compile(r"[_\-\s.]+")


@dataclass(slots=True)
class BatchConfig:
    profile: DocumentProfile
    output_dir: Path
    sensitivity: float = 0.5
    auto_detect: bool = True
    fmt: str = "JPEG"
    dpi: int = 300
    quality: int = 95
    template: str = "{name}_{profile}"
    policy: str = OVERWRITE_RENAME
    apply_enhancement: bool = True
    enhancement: dict = field(default_factory=dict)
    auto_enhance: bool = False
    rotation: int = 0
    auto_orientation: bool = True
    interpolation: str = "Cubic"
    continue_on_error: bool = True

    def processing_settings(self) -> pipeline.ProcessingSettings:
        return pipeline.ProcessingSettings(
            width_mm=self.profile.width_mm,
            height_mm=self.profile.height_mm,
            dpi=self.dpi or self.profile.dpi,
            rotation=self.rotation,
            auto_orientation=self.auto_orientation,
            interpolation=self.interpolation,
            enhancement=dict(self.enhancement),
            apply_enhancement=self.apply_enhancement,
        )


@dataclass(slots=True)
class BatchItemResult:
    source_path: str
    status: str
    output_path: str = ""
    corners: list = field(default_factory=list)
    rotation: int = 0
    confidence: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    size: tuple[int, int] = (0, 0)
    image: np.ndarray | None = None
    duration_ms: float = 0.0  # Processing time in milliseconds

    @property
    def display_name(self) -> str:
        return Path(self.source_path).name

    @property
    def duration_str(self) -> str:
        """Human-readable duration string."""
        ms = self.duration_ms
        if ms < 1000:
            return f"{ms:.0f} ms"
        elif ms < 60000:
            return f"{ms / 1000:.1f} s"
        else:
            return f"{ms / 60000:.1f} min"


def process_file(
    path: Path | str, config: BatchConfig, save_output: bool = True
) -> BatchItemResult:
    """Process one file; never raises for image-level problems.

    ``save_output=False`` corrects the image without writing it, which is what
    paired PDF export needs (it combines the two sides itself).
    """

    source = Path(path)
    start_time = time.perf_counter()
    try:
        loaded = load_image(source)
    except ImageLoadError as exc:
        return BatchItemResult(str(source), STATUS_FAILED, error=str(exc), duration_ms=(time.perf_counter() - start_time) * 1000)

    try:
        if config.auto_detect:
            quad, detection = image_detector.suggest_corners(loaded.image, config.sensitivity)
            confidence = float(detection.confidence)
            if detection.quad is None or not detection.success:
                detail = detection.message or "The document boundary could not be detected."
                return BatchItemResult(
                    str(source),
                    STATUS_REVIEW,
                    corners=detection.as_list(),
                    confidence=confidence,
                    error=detail + " Open it in the Correction Studio to set the corners.",
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )
        else:
            quad = corner_detection.default_quad(loaded.image)
            confidence = 0.0

        settings = config.processing_settings()
        if config.auto_enhance:
            settings.enhancement = enhancement.auto_enhance_params(loaded.image)
        document = pipeline.correct_document(
            loaded.image, quad, settings, analyze_quality=True
        )
    except Exception as exc:  # noqa: BLE001 - process_file must never raise
        # Covers ValueError, ExportError and unexpected errors such as
        # cv2.error from malformed detections; the worker reports it as a
        # failed row instead of aborting the batch.
        return BatchItemResult(str(source), STATUS_FAILED, error=str(exc), duration_ms=(time.perf_counter() - start_time) * 1000)

    warnings = [issue.message for issue in (document.quality.problems if document.quality else [])]

    if not save_output:
        return BatchItemResult(
            str(source),
            STATUS_SUCCESS,
            corners=[[float(x), float(y)] for x, y in document.corners],
            rotation=int(document.rotation),
            confidence=confidence,
            warnings=warnings,
            size=document.size,
            image=document.image,
            duration_ms=(time.perf_counter() - start_time) * 1000,
        )

    output_path = ""
    try:
        fmt = (config.fmt or "JPEG").upper()
        if fmt == "PDF":
            stem = sanitize_filename(source.stem, "document")
            filename = build_filename(
                config.template, name=stem, profile=config.profile.name,
                dpi=config.dpi, extension=".pdf", include_side=False,
            )
            target = Path(config.output_dir) / filename
            if same_path(target, source):
                target = unique_path(target)
            resolved = resolve_target(target, config.policy)
            if resolved is None:
                return BatchItemResult(
                    str(source),
                    STATUS_FAILED,
                    error="The output file already exists and the policy is 'skip'.",
                    warnings=warnings,
                    confidence=confidence,
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )
            build_pdf(
                resolved,
                [document.image],
                page_mode="physical",
                dpi=config.dpi,
                quality=config.quality,
                physical_mm=(config.profile.width_mm, config.profile.height_mm),
                policy="replace" if resolved == target else OVERWRITE_RENAME,
            )
            output_path = str(resolved)
        else:
            if fmt not in RASTER_FORMATS:
                fmt = "JPEG"
            filename = build_filename(
                config.template,
                name=source.stem,
                profile=config.profile.name,
                dpi=config.dpi,
                extension=FORMAT_EXTENSIONS[fmt],
                include_side=False,
            )
            target = Path(config.output_dir) / filename
            if same_path(target, source):
                target = unique_path(target)
            result = save_raster(
                target,
                document.image,
                fmt,
                dpi=config.dpi,
                quality=config.quality,
                policy=config.policy,
            )
            if result.skipped:
                return BatchItemResult(
                    str(source),
                    STATUS_FAILED,
                    error="An output file already exists and the policy is 'skip'.",
                    warnings=warnings,
                    confidence=confidence,
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )
            output_path = str(result.path)
    except (ExportError, OSError) as exc:
        return BatchItemResult(
            str(source), STATUS_FAILED, error=str(exc), warnings=warnings, confidence=confidence, duration_ms=(time.perf_counter() - start_time) * 1000
        )

    return BatchItemResult(
        str(source),
        STATUS_SUCCESS,
        output_path=output_path,
        corners=[[float(x), float(y)] for x, y in document.corners],
        rotation=int(document.rotation),
        confidence=confidence,
        warnings=warnings,
        size=document.size,
        image=document.image,
        duration_ms=(time.perf_counter() - start_time) * 1000,
    )


def collect_images(paths: list[Path | str]) -> list[Path]:
    """Expand folders into supported image files, preserving order."""

    seen: dict[str, Path] = {}
    for entry in paths:
        path = Path(entry)
        if path.is_dir():
            try:
                for child in list_images_in_folder(path, recursive=False):
                    seen[str(child.resolve()).lower()] = child
            except ImageLoadError as exc:
                logger.warning("Folder skipped: %s", exc)
        elif path.is_file() and is_supported(path):
            seen[str(path.resolve()).lower()] = path
    return list(seen.values())


# ------------------------------------------------------------------ pairing
def filename_tokens(path: Path | str) -> list[str]:
    return [token for token in _SPLIT.split(Path(path).stem.lower()) if token]


def side_from_filename(path: Path | str) -> str:
    tokens = filename_tokens(path)
    if not tokens:
        return ""
    if tokens[-1] in FRONT_WORDS:
        return "front"
    if tokens[-1] in BACK_WORDS:
        return "back"
    for token in tokens:
        if token in FRONT_WORDS:
            return "front"
        if token in BACK_WORDS:
            return "back"
    return ""


def pair_key(path: Path | str) -> str:
    tokens = [token for token in filename_tokens(path) if token not in FRONT_WORDS | BACK_WORDS]
    if tokens:
        return "_".join(tokens)
    # Side-only names (F.jpg / B.jpg) carry no document tokens: group by the
    # containing folder so such siblings still pair up.
    parent = Path(path).parent.name.strip().lower()
    return parent or "documents"


@dataclass(slots=True)
class PairGroup:
    document_id: str
    front: Path | None = None
    back: Path | None = None
    profile_name: str = ""
    conflicts: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.front is not None and self.back is not None

    def paths(self) -> list[Path]:
        return [path for path in (self.front, self.back) if path is not None]


def pair_by_filename(paths: list[Path | str]) -> list[PairGroup]:
    """Group obvious front/back filenames, leaving the rest unpaired."""

    grouped: dict[str, PairGroup] = {}
    for entry in paths:
        path = Path(entry)
        side = side_from_filename(path)
        if not side:
            continue
        key = pair_key(path)
        group = grouped.setdefault(key, PairGroup(document_id=key))
        if side == "front":
            if group.front is None:
                group.front = path
            else:
                group.conflicts.append(
                    f"duplicate front: {Path(path).name} (kept {Path(group.front).name})"
                )
        elif side == "back":
            if group.back is None:
                group.back = path
            else:
                group.conflicts.append(
                    f"duplicate back: {Path(path).name} (kept {Path(group.back).name})"
                )
    return sorted(grouped.values(), key=lambda g: g.document_id)


def make_pairs(entries: list[tuple[Path, str, str]]) -> list[PairGroup]:
    """Build groups from explicit ``(path, side, document_id)`` assignments."""

    groups: dict[str, PairGroup] = {}
    for path, side, document_id in entries:
        key = document_id or pair_key(path)
        group = groups.setdefault(key, PairGroup(document_id=key))
        if side == "front":
            if group.front is None:
                group.front = path
            else:
                group.conflicts.append(
                    f"duplicate front: {Path(path).name} (kept {Path(group.front).name})"
                )
        elif side == "back":
            if group.back is None:
                group.back = path
            else:
                group.conflicts.append(
                    f"duplicate back: {Path(path).name} (kept {Path(group.back).name})"
                )
        else:
            group.front = group.front or path
    return list(groups.values())


def export_pairs_to_pdf(
    pairs: list[PairGroup],
    config: BatchConfig,
    output_dir: Path | str,
) -> dict:
    """Correct both sides of each pair and write one PDF per complete document.

    Returns ``{"paths": [...], "errors": [...]}``. A group is only written when
    *both* sides process successfully, so a failed side never produces a
    misleading one-page document.
    """

    paths: list[str] = []
    errors: list[str] = []
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for group in pairs:
        for conflict in group.conflicts:
            errors.append(f"{group.document_id}: {conflict}.")
        if not group.complete:
            missing = "front" if group.front is None else "back"
            errors.append(f"{group.document_id}: the {missing} image is missing.")
            continue
        images: list[np.ndarray] = []
        failed = False
        for side, path in (("front", group.front), ("back", group.back)):
            assert path is not None
            outcome = process_file(path, config, save_output=False)
            if outcome.status != STATUS_SUCCESS or outcome.image is None:
                message = outcome.error or "the image could not be corrected."
                errors.append(f"{group.document_id} ({side}): {message}")
                failed = True
                break
            images.append(outcome.image)
        if failed:
            continue
        filename = sanitize_filename(f"{group.document_id}_{config.profile.filename_prefix or 'document'}")
        try:
            target = build_pdf(
                output / f"{filename}.pdf",
                images,
                page_mode="physical",
                dpi=config.dpi,
                quality=config.quality,
                physical_mm=(config.profile.width_mm, config.profile.height_mm),
                policy=config.policy,
            )
        except ExportError as exc:
            logger.error("Pair PDF failed for %s: %s", group.document_id, exc)
            errors.append(f"{group.document_id}: {exc}")
            continue
        if target:
            paths.append(str(target))
        else:
            errors.append(
                f"{group.document_id}: an existing PDF was skipped by the overwrite policy."
            )
    return {"paths": paths, "errors": errors}


class BatchService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def default_config(self, profile: DocumentProfile) -> BatchConfig:
        fmt = str(self.config.get("default_format", "JPEG")).upper()
        if fmt == "PDF":
            fmt = "JPEG"
        return BatchConfig(
            profile=profile,
            output_dir=Path(str(self.config.get("output_dir"))),
            sensitivity=float(self.config.get("detection_sensitivity", 0.5)),
            auto_detect=bool(self.config.get("batch_auto_detect", True)),
            fmt=fmt,
            dpi=int(self.config.get("default_dpi", profile.dpi)),
            quality=int(self.config.get("jpeg_quality", 95)),
            template=str(self.config.get("filename_template", "{name}_{profile}")),
            policy=str(self.config.get("overwrite_policy", OVERWRITE_RENAME)),
            auto_enhance=bool(self.config.get("auto_enhance", False)),
            interpolation=str(self.config.get("interpolation", "Cubic")),
            continue_on_error=bool(self.config.get("batch_continue_on_error", True)),
        )

    def collect(self, paths: list[Path | str]) -> list[Path]:
        return collect_images(paths)
