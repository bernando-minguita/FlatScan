"""Export naming, conflict handling and format orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from app.config import AppConfig
from app.constants import (
    DEFAULT_FILENAME_TEMPLATE,
    OVERWRITE_RENAME,
    RASTER_FORMATS,
)
from core import image_exporter, pdf_handler
from core.image_exporter import FORMAT_EXTENSIONS, ExportError, SaveResult
from core.image_loader import load_image

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOKEN_PATTERN = re.compile(r"\{(\w+)\}")

# Windows refuses these device names even with an extension.
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(slots=True)
class ExportOptions:
    fmt: str = "JPEG"
    dpi: int = 300
    quality: int = 95
    output_dir: Path = field(default_factory=Path)
    template: str = DEFAULT_FILENAME_TEMPLATE
    policy: str = OVERWRITE_RENAME
    include_profile: bool = True
    include_side: bool = True
    page_mode: str = "physical"
    margin_mm: float = 0.0
    embed_dpi: bool = True

    def normalized_format(self) -> str:
        value = (self.fmt or "JPEG").upper()
        return value if value in FORMAT_EXTENSIONS else "JPEG"


@dataclass(slots=True)
class ExportItem:
    display_name: str
    profile_name: str = ""
    side: str = ""
    path: Path | None = None
    image: np.ndarray | None = None
    index: int = 0
    width_mm: float | None = None
    height_mm: float | None = None
    document_id: str = ""
    source_path: Path | None = None

    def load(self) -> np.ndarray:
        if self.image is not None:
            return self.image
        if self.path is None:
            raise ExportError("The item has no image or file path.")
        return load_image(self.path).image

    @property
    def stem(self) -> str:
        if self.path is not None:
            return self.path.stem
        return Path(self.display_name).stem or "document"


def sanitize_filename(text: str, fallback: str = "document") -> str:
    cleaned = _INVALID_CHARS.sub("_", str(text or "")).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned[:120] or fallback
    if cleaned.split(".", 1)[0].upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def build_filename(
    template: str,
    *,
    name: str,
    profile: str = "",
    side: str = "",
    index: int = 0,
    dpi: int = 300,
    extension: str = ".jpg",
    include_side: bool = True,
    include_profile: bool = True,
    document_id: str = "",
) -> str:
    """Expand a filename template into a safe file name."""

    now = datetime.now()
    values = {
        "name": sanitize_filename(name, "document"),
        "profile": sanitize_filename(profile, "profile") if profile else "profile",
        "side": sanitize_filename(side, "side") if side else "",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H%M%S"),
        "dpi": str(int(dpi)),
        "index": f"{index:03d}",
        "document_id": sanitize_filename(document_id) if document_id else "",
    }
    template = (template or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE
    used_tokens = set(_TOKEN_PATTERN.findall(template))
    result = _TOKEN_PATTERN.sub(lambda match: values.get(match.group(1), match.group(0)), template)

    extras: list[str] = []
    if include_profile and profile and "profile" not in used_tokens:
        extras.append(values["profile"])
    if include_side and side and "side" not in used_tokens:
        extras.append(values["side"])
    if extras:
        result = f"{result}_{'_'.join(extras)}"

    result = sanitize_filename(result, "document")
    if not result.lower().endswith(extension.lower()):
        result += extension
    return result


class ExportService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def default_options(self) -> ExportOptions:
        fmt = str(self.config.get("default_format", "JPEG")).upper()
        if fmt not in FORMAT_EXTENSIONS:
            fmt = "JPEG"
        return ExportOptions(
            fmt=fmt,
            dpi=int(self.config.get("default_dpi", 300)),
            quality=int(self.config.get("jpeg_quality", 95)),
            output_dir=Path(str(self.config.get("output_dir"))),
            template=str(self.config.get("filename_template", DEFAULT_FILENAME_TEMPLATE)),
            policy=str(self.config.get("overwrite_policy", OVERWRITE_RENAME)),
        )

    # -------------------------------------------------------------- raster
    def export_item(
        self,
        item: ExportItem,
        options: ExportOptions,
        confirm_replace: Callable[[Path], bool] | None = None,
    ) -> SaveResult | None:
        fmt = options.normalized_format()
        if fmt not in RASTER_FORMATS:
            raise ExportError("This format is exported through the PDF writer.")
        image = item.load()
        filename = build_filename(
            options.template,
            name=item.stem,
            profile=item.profile_name,
            side=item.side,
            index=item.index,
            dpi=options.dpi,
            extension=FORMAT_EXTENSIONS[fmt],
            include_profile=options.include_profile,
            include_side=options.include_side,
            document_id=item.document_id,
        )
        target = Path(options.output_dir) / filename
        policy = options.policy
        # An export must never overwrite the original photo, even when the
        # output folder is the source folder and the name template matches.
        if item.source_path is not None and image_exporter.same_path(target, item.source_path):
            target = image_exporter.unique_path(target)
            policy = "rename"
        if policy == "replace" and target.exists():
            # The confirmation must not depend on unrelated options such as
            # DPI metadata embedding; without this guard the file would be
            # overwritten silently whenever embed_dpi is off.
            if confirm_replace is not None and not confirm_replace(target):
                return SaveResult(path=target, skipped=True, declined=True)
        return image_exporter.save_raster(
            target,
            image,
            fmt,
            dpi=options.dpi,
            quality=options.quality,
            policy=policy,
        )

    def export_items_to_pdf(
        self,
        items: list[ExportItem],
        options: ExportOptions,
        output_stem: str = "documents",
        confirm_replace: Callable[[Path], bool] | None = None,
    ) -> Path | None:
        if not items:
            raise ExportError("There are no images to export.")
        first = items[0]
        filename = build_filename(
            options.template,
            name=output_stem or first.stem,
            profile=first.profile_name,
            index=0,
            dpi=options.dpi,
            extension=".pdf",
            include_side=False,
        )
        target = Path(options.output_dir) / filename
        # Never overwrite one of the source files, even when the output folder
        # is also the source folder and the template reproduces its name.
        for source in (item.source_path for item in items if item.source_path is not None):
            if image_exporter.same_path(target, source):
                target = image_exporter.unique_path(target)
                break
        if target.exists() and options.policy == "replace" and confirm_replace is not None:
            if not confirm_replace(target):
                return None
        images = [item.load() for item in items]
        physical = None
        item = items[0]
        if item.width_mm and item.height_mm:
            physical = (item.width_mm, item.height_mm)
        return pdf_handler.build_pdf(
            target,
            images,
            page_mode=options.page_mode,
            dpi=options.dpi,
            quality=options.quality,
            physical_mm=physical,
            policy=options.policy,
            margin_mm=options.margin_mm,
        )
