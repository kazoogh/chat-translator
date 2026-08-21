from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from game_chat_translator.capture.base import RawFrame

if TYPE_CHECKING:
    from game_chat_translator.profiles.schema import GameProfile


@dataclass(frozen=True, slots=True)
class PreprocessConfig:
    scale: int = 2
    contrast: float = 1.2
    sharpen: bool = True
    text_colors: tuple[str, ...] = ()
    color_tolerance: int = 54

    def __post_init__(self) -> None:
        if not 1 <= self.scale <= 4:
            raise ValueError("preprocess scale must be between 1 and 4")
        if not 0.1 <= self.contrast <= 5.0:
            raise ValueError("preprocess contrast must be between 0.1 and 5.0")
        if not 0 <= self.color_tolerance <= 255:
            raise ValueError("color tolerance must be between 0 and 255")
        for color in self.text_colors:
            if len(color) != 7 or not color.startswith("#"):
                raise ValueError("text colors must use #RRGGBB")
            int(color[1:], 16)

    @classmethod
    def from_profile(cls, profile: GameProfile) -> PreprocessConfig:
        rules = profile.preprocess
        return cls(
            scale=rules.scale,
            contrast=rules.contrast,
            sharpen=rules.sharpen,
            text_colors=rules.text_colors,
        )


@dataclass(frozen=True, slots=True)
class PreprocessedImage:
    pixels: bytes
    width: int
    height: int
    channels: int = 1


class ReferencePreprocessor:
    """Deterministic, dependency-free grayscale preprocessing used by tests/fallback."""

    def process(self, frame: RawFrame, config: PreprocessConfig) -> PreprocessedImage:
        if frame.pixel_format != "BGRA":
            raise ValueError("reference preprocessor requires BGRA input")
        if len(frame.pixels) != frame.width * frame.height * 4:
            raise ValueError("frame buffer length does not match dimensions")
        allowed = tuple(_parse_color(color) for color in config.text_colors)
        grayscale = bytearray(frame.width * frame.height)
        for index in range(frame.width * frame.height):
            blue, green, red, _alpha = frame.pixels[index * 4 : index * 4 + 4]
            if allowed and not any(
                max(abs(red - target[0]), abs(green - target[1]), abs(blue - target[2]))
                <= config.color_tolerance
                for target in allowed
            ):
                value = 0
            else:
                luminance = round(0.299 * red + 0.587 * green + 0.114 * blue)
                value = min(255, max(0, round((luminance - 128) * config.contrast + 128)))
            grayscale[index] = value
        if config.sharpen and frame.width >= 3 and frame.height >= 3:
            grayscale = _sharpen(grayscale, frame.width, frame.height)
        return _nearest_upscale(grayscale, frame.width, frame.height, config.scale)


class OpenCvPreprocessor:
    """Production OpenCV preprocessing, imported lazily for portable CI."""

    def process(self, frame: RawFrame, config: PreprocessConfig) -> PreprocessedImage:
        if frame.pixel_format != "BGRA":
            raise ValueError("OpenCV preprocessor requires BGRA input")
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("install the pinned vision extra for OpenCV preprocessing") from exc
        image = np.frombuffer(frame.pixels, dtype=np.uint8).reshape((frame.height, frame.width, 4))
        bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if config.text_colors:
            mask: Any = np.zeros((frame.height, frame.width), dtype=np.uint8)
            for color in config.text_colors:
                red, green, blue = _parse_color(color)
                target = np.array([blue, green, red], dtype=np.int16)
                distance = np.max(np.abs(bgr.astype(np.int16) - target), axis=2)
                mask = cv2.bitwise_or(
                    mask, (distance <= config.color_tolerance).astype(np.uint8) * 255
                )
            gray: Any = cv2.bitwise_and(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), mask)
        else:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.convertScaleAbs(gray, alpha=config.contrast, beta=128 * (1 - config.contrast))
        if config.sharpen:
            gray = cv2.filter2D(gray, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))
        if config.scale != 1:
            gray = cv2.resize(
                gray,
                (frame.width * config.scale, frame.height * config.scale),
                interpolation=cv2.INTER_CUBIC,
            )
        return PreprocessedImage(bytes(gray.tobytes()), int(gray.shape[1]), int(gray.shape[0]))


def _parse_color(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _nearest_upscale(pixels: bytearray, width: int, height: int, scale: int) -> PreprocessedImage:
    if scale == 1:
        return PreprocessedImage(bytes(pixels), width, height)
    output_width = width * scale
    output = bytearray(output_width * height * scale)
    for y in range(height):
        expanded = bytearray()
        for value in pixels[y * width : (y + 1) * width]:
            expanded.extend([value] * scale)
        for offset in range(scale):
            start = (y * scale + offset) * output_width
            output[start : start + output_width] = expanded
    return PreprocessedImage(bytes(output), output_width, height * scale)


def _sharpen(pixels: bytearray, width: int, height: int) -> bytearray:
    output = bytearray(pixels)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            index = y * width + x
            value = (
                5 * pixels[index]
                - pixels[index - 1]
                - pixels[index + 1]
                - pixels[index - width]
                - pixels[index + width]
            )
            output[index] = min(255, max(0, value))
    return output
