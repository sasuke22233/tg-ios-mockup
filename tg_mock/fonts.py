"""
Шрифты: SF Pro (переменный шрифт Apple) + подключение эмодзи.

Если файл SF Pro не найден — автоматически используется системный
DejaVu/Noto, чтобы шаблон всё равно собирался (качество чуть ниже).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional, Tuple

from PIL import ImageFont

from . import emoji as emoji_mod

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)

SF_FONT_CANDIDATES = (
    os.path.join(_PROJECT, "assets", "fonts", "SF-Pro.ttf"),
    os.path.join(_PROJECT, "assets", "fonts", "SFProText-Regular.ttf"),
    os.path.join(_PROJECT, "assets", "fonts", "SF-Pro-Display-Regular.ttf"),
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

FALLBACK_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)

# Названия начертаний -> вес переменного шрифта SF Pro (ось wght)
WEIGHTS: Dict[str, int] = {
    "ultralight": 100,
    "thin": 200,
    "light": 300,
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "heavy": 800,
    "black": 900,
}


def _first_existing(paths) -> Optional[str]:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


class FontBook:
    """Кэш шрифтов с настройкой оси переменного шрифта."""

    def __init__(self, sf_path: Optional[str] = None, emoji_path: Optional[str] = None):
        self.sf_path = sf_path or _first_existing(SF_FONT_CANDIDATES)
        self.is_variable = False
        self.variable_axes: Optional[list] = None
        if self.sf_path:
            try:
                probe = ImageFont.truetype(self.sf_path, 32)
                axes = probe.get_variation_axes() or []
                if axes:
                    self.is_variable = True
                    self.variable_axes = [a["name"].decode() if isinstance(a["name"], bytes) else a["name"] for a in axes]
            except Exception:
                self.sf_path = None
        self.fallback_path = _first_existing(FALLBACK_CANDIDATES)
        self._cache: Dict[Tuple[int, float], ImageFont.FreeTypeFont] = {}
        self._metrics_cache: Dict[Tuple[int, float], Tuple[int, int]] = {}
        self.emoji = emoji_mod.EmojiRenderer(emoji_path, fallback_font_path=self.fallback_path)

    # ---------- текстовый шрифт ----------
    def get(self, weight: int = 400, size_px: float = 16.0) -> ImageFont.FreeTypeFont:
        size_px = float(size_px)
        key = (int(weight), round(size_px, 2))
        if key in self._cache:
            return self._cache[key]
        font = None
        if self.sf_path:
            try:
                font = ImageFont.truetype(self.sf_path, int(round(size_px)))
                if self.is_variable and self.variable_axes:
                    values = []
                    for name in self.variable_axes:
                        if name == "Weight":
                            values.append(weight)
                        elif name == "Optical Size":
                            # opsz: 17 для мелкого текста, 28 для крупного
                            values.append(max(17.0, min(28.0, size_px / 3.0)))
                        elif name == "Width":
                            values.append(100)
                        else:
                            values.append(None)
                    try:
                        font.set_variation_by_axes([v if v is not None else 400 for v in values])
                    except Exception:
                        pass
            except Exception:
                font = None
        if font is None:
            bold = weight >= 600 and self.fallback_path and "Bold" in self.fallback_path
            path = self.fallback_path or ""
            if bold:
                cand = path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                if os.path.exists(cand):
                    path = cand
            font = ImageFont.truetype(path, int(round(size_px))) if path else ImageFont.load_default()
        self._cache[key] = font
        return font

    # ---------- метрики ----------
    def ascent_descent(self, weight: int = 400, size_px: float = 16.0) -> Tuple[int, int]:
        key = (int(weight), round(float(size_px), 2))
        if key not in self._metrics_cache:
            self._metrics_cache[key] = self.get(weight, size_px).getmetrics()
        return self._metrics_cache[key]

    def text_width(self, text: str, weight: int = 400, size_px: float = 16.0) -> float:
        return float(self.get(weight, size_px).getlength(text))


def default_fontbook() -> FontBook:
    return FontBook()
