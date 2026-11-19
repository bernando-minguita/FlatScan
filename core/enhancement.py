"""Image enhancement operations.

Enhancement is applied to a *copy* of the perspective-corrected image, so the
corrected master can always be re-exported without the adjustments.
"""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_PARAMS: dict = {
    "brightness": 0,      # -100 .. 100
    "contrast": 0,        # -100 .. 100
    "saturation": 0,      # -100 .. 100
    "sharpness": 0,       # 0 .. 100
    "gamma": 1.0,         # 0.30 .. 3.00
    "denoise": 0,         # 0 .. 100
    "color_boost": 0,     # 0 .. 100
    "white_balance": False,
    "grayscale": False,
}

LIMITS: dict[str, tuple[float, float]] = {
    "brightness": (-100, 100),
    "contrast": (-100, 100),
    "saturation": (-100, 100),
    "sharpness": (0, 100),
    "gamma": (0.3, 3.0),
    "denoise": (0, 100),
    "color_boost": (0, 100),
}


def normalize_params(params: dict | None) -> dict:
    result = dict(DEFAULT_PARAMS)
    if not params:
        return result
    for key in DEFAULT_PARAMS:
        if key not in params:
            continue
        value = params[key]
        if isinstance(DEFAULT_PARAMS[key], bool):
            result[key] = bool(value)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        low, high = LIMITS.get(key, (number, number))
        result[key] = max(low, min(high, number))
    result["gamma"] = max(0.3, min(3.0, float(result["gamma"])))
    return result


def is_identity(params: dict) -> bool:
    params = normalize_params(params)
    return (
        abs(params["brightness"]) < 1e-6
        and abs(params["contrast"]) < 1e-6
        and abs(params["saturation"]) < 1e-6
        and abs(params["sharpness"]) < 1e-6
        and abs(params["color_boost"]) < 1e-6
        and abs(params["gamma"] - 1.0) < 1e-6
        and params["denoise"] < 1
        and not params["white_balance"]
        and not params["grayscale"]
    )


def _tone_lut(brightness: float, contrast: float, gamma: float) -> np.ndarray:
    values = np.arange(256, dtype=np.float32) / 255.0
    if abs(gamma - 1.0) > 1e-6:
        values = np.power(np.clip(values, 0.0, 1.0), 1.0 / max(0.05, gamma))
    values *= 255.0
    if abs(contrast) > 1e-6:
        factor = (259.0 * (contrast + 255.0)) / (255.0 * (259.0 - contrast))
        values = (values - 128.0) * factor + 128.0
    values = values + brightness
    return np.clip(values, 0, 255).astype(np.uint8)


def apply_white_balance(image: np.ndarray) -> np.ndarray:
    """Simple gray-world white balance."""

    result = image.astype(np.float32)
    channel_means = result.reshape(-1, 3).mean(axis=0)
    target = float(np.mean(channel_means))
    if target <= 1e-3:
        return image.copy()
    for index in range(3):
        mean = max(channel_means[index], 1.0)
        result[:, :, index] *= target / mean
    return np.clip(result, 0, 255).astype(np.uint8)


def _adjust_saturation(image: np.ndarray, saturation: float, color_boost: float) -> np.ndarray:
    scale = 1.0 + (saturation / 100.0) + (color_boost / 100.0) * 0.5
    if abs(scale - 1.0) < 1e-4:
        return image
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _unsharp(image: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0:
        return image
    strength = (amount / 100.0) * 1.6
    blurred = cv2.GaussianBlur(image, (0, 0), 1.4)
    return cv2.addWeighted(image, 1.0 + strength, blurred, -strength, 0)


def _denoise(image: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0:
        return image
    h = max(1.0, 2.0 + amount * 0.10)
    return cv2.fastNlMeansDenoisingColored(image, None, h, h, 7, 21)


def apply_enhancements(image: np.ndarray, params: dict | None) -> np.ndarray:
    """Apply all enabled adjustments and return a new array."""

    if image is None or image.size == 0:
        raise ValueError("No image supplied for enhancement.")
    settings = normalize_params(params)
    if is_identity(settings):
        return image.copy()

    result = image.copy()
    if settings["white_balance"]:
        result = apply_white_balance(result)
    if settings["grayscale"]:
        gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
        result = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    else:
        if abs(settings["saturation"]) > 1e-6 or abs(settings["color_boost"]) > 1e-6:
            result = _adjust_saturation(result, settings["saturation"], settings["color_boost"])
    if settings["gamma"] != 1.0 or settings["brightness"] or settings["contrast"]:
        lut = _tone_lut(settings["brightness"], settings["contrast"], settings["gamma"])
        result = cv2.LUT(result, lut)
    if settings["denoise"] > 0:
        result = _denoise(result, settings["denoise"])
    if settings["sharpness"] > 0:
        result = _unsharp(result, settings["sharpness"])
    return result


def estimate_sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def auto_enhance_params(image: np.ndarray, mode: str = "balanced") -> dict:
    """Estimate sensible adjustments from the image histogram.

    This is deliberately conservative: it fixes exposure and colour cast and
    adds a little local contrast, without pretending to restore lost detail.
    """

    params = dict(DEFAULT_PARAMS)
    if image is None or image.size == 0:
        return params

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mean = float(gray.mean())
    std = float(gray.std())
    p2, p98 = np.percentile(gray, (2, 98))

    gamma = 1.0
    if mean < 90:
        gamma = 1.0 + min(0.75, (110 - mean) / 110.0)
    elif mean > 180:
        gamma = max(0.55, 1.0 - (mean - 170) / 220.0)

    contrast = 0.0
    spread = max(1.0, float(p98 - p2))
    if spread < 150:
        contrast = min(28.0, (150.0 - spread) * 0.35)
    if std < 35:
        contrast = max(contrast, min(24.0, (40.0 - std) * 0.8))
    elif mode == "strong" and std < 60:
        contrast = min(20.0, (60.0 - std) * 0.4)

    brightness = 0.0
    if mean < 60:
        brightness = min(18.0, (65.0 - mean) * 0.4)
    elif mean > 215:
        brightness = max(-18.0, (215.0 - mean) * 0.4)

    params.update(
        {
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
            "gamma": round(gamma, 2),
            "white_balance": True,
            "sharpness": 28.0 if mode in ("balanced", "strong") else 12.0,
            "color_boost": 6.0 if mode == "strong" else 0.0,
            "denoise": 12.0 if float(np.std(np.abs(np.diff(gray.astype(np.float32), axis=1)))) > 18 else 0.0,
        }
    )
    if mode == "document":
        params["grayscale"] = False
        params["contrast"] = max(params["contrast"], 12.0)
    return params
