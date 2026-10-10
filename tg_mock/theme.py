"""Цветовые темы Telegram (тёмная / светлая) и параметры устройств iPhone."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

RGBA = Tuple[int, int, int, int]


def hex_rgba(value: str, alpha: int = 255) -> RGBA:
    v = value.lstrip("#")
    if len(v) == 6:
        r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
    elif len(v) == 8:
        r, g, b, alpha = (int(v[i:i + 2], 16) for i in (0, 2, 4, 6))
    else:
        raise ValueError(f"Некорректный цвет: {value}")
    return (r, g, b, alpha)


@dataclass
class Theme:
    name: str = "dark"

    # экраны
    chat_bg: RGBA = (23, 33, 43, 255)
    chat_bg_2: RGBA = (18, 26, 34, 255)        # для градиента/узорa
    panel_bg: RGBA = (28, 39, 51, 255)         # навбар и нижняя панель
    separator: RGBA = (0, 0, 0, 90)
    home_indicator: RGBA = (255, 255, 255, 150)

    # текст
    text: RGBA = (255, 255, 255, 255)
    text_secondary: RGBA = (125, 139, 153, 255)
    status_bar_text: RGBA = (255, 255, 255, 255)
    accent: RGBA = (94, 169, 240, 255)
    accent_contrast: RGBA = (255, 255, 255, 255)

    # пузырь сообщения
    bubble: RGBA = (24, 37, 51, 255)
    bubble_border: RGBA = (0, 0, 0, 0)
    bubble_text: RGBA = (255, 255, 255, 255)
    bubble_secondary: RGBA = (125, 139, 153, 255)
    bubble_link: RGBA = (94, 169, 240, 255)
    bubble_mono_bg: RGBA = (120, 140, 160, 70)
    bubble_spoiler_bg: RGBA = (110, 130, 150, 150)

    # плашка с датой
    chip_bg: RGBA = (0, 0, 0, 80)
    chip_text: RGBA = (255, 255, 255, 190)

    # реакции
    reaction_bg: RGBA = (43, 59, 75, 255)
    reaction_text: RGBA = (125, 139, 153, 255)
    reaction_bg_selected: RGBA = (94, 169, 240, 46)
    reaction_text_selected: RGBA = (94, 169, 240, 255)
    reaction_border_selected: RGBA = (94, 169, 240, 255)

    # инлайн-кнопки
    button_bg: RGBA = (43, 59, 75, 255)
    button_text: RGBA = (94, 169, 240, 255)

    # иконки
    icon: RGBA = (255, 255, 255, 255)
    icon_secondary: RGBA = (255, 255, 255, 110)
    mono_font_weight: int = 400

    def style_colors(self) -> Dict[str, RGBA]:
        return {
            "plain": self.bubble_text,
            "bold": self.bubble_text,
            "italic": self.bubble_text,
            "mono": self.bubble_text,
            "link": self.bubble_link,
            "spoiler": (0, 0, 0, 0),
            "mono_bg": self.bubble_mono_bg,
            "spoiler_bg": self.bubble_spoiler_bg,
        }

    def with_overrides(self, overrides: Dict[str, object]) -> "Theme":
        if not overrides:
            return self
        theme = Theme(**{**self.__dict__})
        for key, value in overrides.items():
            if not hasattr(theme, key):
                raise KeyError(f"Неизвестный ключ темы: {key}")
            if isinstance(value, str):
                value = hex_rgba(value) if value.startswith("#") and getattr(theme, key).__class__ is tuple else value
            setattr(theme, key, value)
        return theme


DARK = Theme(name="dark")

LIGHT = Theme(
    name="light",
    chat_bg=(240, 242, 245, 255),
    chat_bg_2=(228, 233, 238, 255),
    panel_bg=(249, 250, 251, 255),
    separator=(0, 0, 0, 28),
    home_indicator=(0, 0, 0, 110),
    text=(0, 0, 0, 255),
    text_secondary=(138, 143, 153, 255),
    status_bar_text=(0, 0, 0, 255),
    accent=(0, 126, 229, 255),
    accent_contrast=(255, 255, 255, 255),
    bubble=(255, 255, 255, 255),
    bubble_border=(0, 0, 0, 22),
    bubble_text=(0, 0, 0, 255),
    bubble_secondary=(138, 143, 153, 255),
    bubble_link=(0, 126, 229, 255),
    bubble_mono_bg=(120, 130, 145, 45),
    bubble_spoiler_bg=(140, 148, 158, 160),
    chip_bg=(0, 0, 0, 45),
    chip_text=(90, 96, 106, 255),
    reaction_bg=(237, 239, 242, 255),
    reaction_text=(108, 114, 122, 255),
    reaction_bg_selected=(0, 126, 229, 30),
    reaction_text_selected=(0, 126, 229, 255),
    reaction_border_selected=(0, 126, 229, 255),
    button_bg=(255, 255, 255, 255),
    button_text=(0, 126, 229, 255),
    icon=(0, 0, 0, 255),
    icon_secondary=(0, 0, 0, 90),
)

THEMES = {"dark": DARK, "light": LIGHT}


def get_theme(name: str, overrides: Dict[str, object] | None = None) -> Theme:
    base = THEMES.get((name or "dark").lower())
    if base is None:
        raise KeyError(f"Неизвестная тема: {name}. Доступны: {', '.join(THEMES)}")
    return base.with_overrides(overrides or {})


@dataclass
class Device:
    """Геометрия конкретной модели iPhone (в логических пунктах)."""

    name: str = "iPhone 15 Pro"
    width: float = 430.0
    height: float = 932.0
    scale: int = 3
    style: str = "island"            # island | notch
    cutout_w: float = 125.0
    cutout_h: float = 36.0
    cutout_top: float = 12.0
    status_h: float = 54.0
    nav_h: float = 44.0
    bottom_safe: float = 34.0

    @property
    def pixel_size(self) -> Tuple[int, int]:
        return (int(self.width * self.scale), int(self.height * self.scale))


DEVICES: Dict[str, Device] = {
    "iphone_15_pro": Device(name="iPhone 15 Pro", width=430, height=932, scale=3, style="island",
                            cutout_w=125, cutout_h=36, cutout_top=12),
    "iphone_15_pro_max": Device(name="iPhone 15 Pro Max", width=430, height=932, scale=3, style="island",
                                cutout_w=125, cutout_h=36, cutout_top=12),
    "iphone_14_pro": Device(name="iPhone 14 Pro", width=393, height=852, scale=3, style="island",
                            cutout_w=125, cutout_h=36, cutout_top=12),
    "iphone_13": Device(name="iPhone 13", width=390, height=844, scale=3, style="notch",
                        cutout_w=209, cutout_h=30, cutout_top=0),
    "iphone_x": Device(name="iPhone X", width=375, height=812, scale=3, style="notch",
                       cutout_w=209, cutout_h=30, cutout_top=0),
    "iphone_se3": Device(name="iPhone SE (3gen)", width=375, height=667, scale=2, style="classic",
                         cutout_w=0, cutout_h=0, cutout_top=0, status_h=20, bottom_safe=0),
}


def get_device(name: str) -> Device:
    if name in DEVICES:
        return DEVICES[name]
    if name in {d.name for d in DEVICES.values()}:
        return next(d for d in DEVICES.values() if d.name == name)
    raise KeyError(f"Неизвестное устройство: {name}. Доступны: {', '.join(DEVICES)}")
