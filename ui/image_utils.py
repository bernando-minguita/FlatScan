"""Conversions between OpenCV arrays and Qt images."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage, QPixmap


def bgr_to_qimage(image: np.ndarray) -> QImage:
    if image is None or image.size == 0:
        return QImage()
    array = np.ascontiguousarray(image)
    if array.ndim == 2:
        height, width = array.shape
        return QImage(array.data, width, height, array.strides[0], QImage.Format.Format_Grayscale8).copy()
    height, width, channels = array.shape
    if channels == 1:
        # (h, w, 1) arrays (some cv2 outputs) must not fall into BGR888 with a
        # wrong stride; reinterpret them as 2-D grayscale.
        squeezed = array.reshape(height, width)
        return QImage(
            squeezed.data, width, height, squeezed.strides[0], QImage.Format.Format_Grayscale8
        ).copy()
    if channels == 4:
        return QImage(array.data, width, height, array.strides[0], QImage.Format.Format_ARGB32).copy()
    return QImage(
        array.data, width, height, array.strides[0], QImage.Format.Format_BGR888
    ).copy()


def bgr_to_pixmap(image: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(bgr_to_qimage(image))


def qimage_to_bgr(image: QImage) -> np.ndarray:
    if image.isNull():
        raise ValueError("The clipboard image is empty.")
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = converted.width(), converted.height()
    pointer = converted.constBits()
    array = np.frombuffer(pointer, np.uint8, count=converted.sizeInBytes())
    array = array.reshape(height, converted.bytesPerLine())[:, : width * 3]
    array = array.reshape(height, width, 3)
    return np.ascontiguousarray(array[:, :, ::-1])


def pixmap_size_label(pixmap: QPixmap) -> str:
    return f"{pixmap.width()} × {pixmap.height()} px"
