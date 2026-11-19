"""Image loading from disk, bytes and the clipboard.

All images are handled as BGR ``numpy`` arrays (OpenCV convention). Decoding is
done through Pillow so that non-ASCII Windows paths and EXIF rotation work
without special cases.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.constants import SUPPORTED_IMAGE_EXTENSIONS
from .orientation import orientation_label


class ImageLoadError(Exception):
    """A user-facing image loading failure."""


class UnsupportedFormatError(ImageLoadError):
    pass


@dataclass
class LoadedImage:
    image: np.ndarray
    path: Path | None = None
    file_size: int = 0
    exif_rotated: bool = False
    source_label: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def orientation(self) -> str:
        return orientation_label(self.width, self.height)

    @property
    def file_size_label(self) -> str:
        return human_file_size(self.file_size)

    @property
    def display_name(self) -> str:
        if self.path is not None:
            return self.path.name
        return self.source_label or "Untitled image"


def human_file_size(size: int) -> str:
    if size <= 0:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def _pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
    rgb = pil_image.convert("RGB")
    return np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()


def load_image(path: Path | str) -> LoadedImage:
    file_path = Path(path)
    if not file_path.exists():
        raise ImageLoadError(f"The file does not exist:\n{file_path}")
    if not file_path.is_file():
        raise ImageLoadError("The selected path is not a file.")
    if file_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file format '{file_path.suffix}'. "
            "Supported formats: JPEG, PNG, BMP, TIFF and WebP."
        )
    try:
        with Image.open(file_path) as pil_image:
            exif = pil_image.getexif()
            orientation = int(exif.get(274, 1) or 1) if exif else 1
            upright = ImageOps.exif_transpose(pil_image)
            image = _pil_to_bgr(upright)
    except UnidentifiedImageError as exc:
        raise ImageLoadError(
            "The image could not be decoded. It may be corrupted or in an "
            "unsupported variant of the format."
        ) from exc
    except (OSError, ValueError) as exc:
        raise ImageLoadError(f"The image could not be opened: {exc}") from exc

    if image.size == 0:
        raise ImageLoadError("The image is empty.")
    return LoadedImage(
        image=image,
        path=file_path,
        file_size=file_path.stat().st_size,
        exif_rotated=orientation != 1,
        source_label=file_path.name,
    )


def load_image_bytes(data: bytes, label: str = "Clipboard image") -> LoadedImage:
    try:
        with Image.open(io.BytesIO(data)) as pil_image:
            image = _pil_to_bgr(ImageOps.exif_transpose(pil_image))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageLoadError("The image data could not be decoded.") from exc
    return LoadedImage(image=image, file_size=len(data), source_label=label)


def load_image_array(array: np.ndarray, label: str = "Imported image") -> LoadedImage:
    arr = np.asarray(array)
    if arr.ndim == 2:
        arr = np.dstack([arr] * 3)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ImageLoadError("Unsupported image data.")
    if arr.shape[2] == 4:
        # Transparent regions must not become black: composite over white so
        # the pipeline receives a plain BGR image.
        alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
        rgb = arr[:, :, :3].astype(np.float32)
        white = np.full_like(rgb, 255.0)
        arr = (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)
    return LoadedImage(image=np.ascontiguousarray(arr, dtype=np.uint8), source_label=label)


def thumbnail(image: np.ndarray, max_size: int = 320) -> np.ndarray:
    """Downscale for previews while keeping the aspect ratio."""

    height, width = image.shape[:2]
    if max(height, width) <= max_size:
        return image.copy()
    scale = max_size / float(max(height, width))
    resized = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    import cv2

    return cv2.resize(image, resized, interpolation=cv2.INTER_AREA)


def save_thumbnail(image: np.ndarray, path: Path | str, max_size: int = 320) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    small = thumbnail(image, max_size)
    Image.fromarray(small[:, :, ::-1]).save(target, format="JPEG", quality=82)
    return target


def list_images_in_folder(folder: Path | str, recursive: bool = False) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        raise ImageLoadError(f"Folder not found: {root}")
    iterator = root.rglob("*") if recursive else root.glob("*")
    files = [p for p in iterator if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS]
    return sorted(files, key=lambda p: str(p).lower())


def image_info(path: Path | str) -> dict:
    """Read dimensions without keeping the full image in memory."""

    file_path = Path(path)
    try:
        with Image.open(file_path) as pil_image:
            width, height = pil_image.size
        size = file_path.stat().st_size
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ImageLoadError(f"Could not read image information: {exc}") from exc
    return {
        "width": width,
        "height": height,
        "file_size": size,
        "orientation": orientation_label(width, height),
    }
