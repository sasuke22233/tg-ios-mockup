"""Конфигурация шаблона: читается из JSON, правится руками или из веб-редактора."""

from __future__ import annotations

import dataclasses
import json
import re
import os
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional, Sequence


def plural_ru(n: int, forms: Sequence[str] = ("подписчик", "подписчика", "подписчиков")) -> str:
    n = abs(int(n))
    mod100 = n % 100
    mod10 = n % 10
    if 11 <= mod100 <= 14:
        return forms[2]
    if mod10 == 1:
        return forms[0]
    if 2 <= mod10 <= 4:
        return forms[1]
    return forms[2]


def group_digits(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def format_subscribers(n: Any) -> str:
    """Число (или строка с числом) -> «125 431 подписчик» с русскими окончаниями."""
    if isinstance(n, bool):
        return str(n)
    if isinstance(n, (int, float)):
        return f"{group_digits(int(n))} {plural_ru(int(n))}"
    text = str(n).strip()
    digits = text.replace("\u00a0", "").replace(" ", "").replace("_", "")
    if digits.isdigit():
        value = int(digits)
        return f"{group_digits(value)} {plural_ru(value)}"
    return text


def format_views(n: int, fmt: str = "km") -> str:
    n = int(n)
    if fmt == "raw":
        return group_digits(n)
    if fmt == "ru":
        if n < 1000:
            return str(n)
        if n < 1_000_000:
            v = n / 1000.0
            s = f"{v:.1f}".rstrip("0").rstrip(",")
            return f"{s.replace('.', ',')} тыс."
        v = n / 1_000_000.0
        s = f"{v:.1f}".rstrip("0").rstrip(",")
        return f"{s.replace('.', ',')} млн"
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        v = n / 1000.0
        s = f"{v:.1f}"
        s = s[:-2] if s.endswith(".0") else s
        return f"{s}K"
    v = n / 1_000_000.0
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return f"{s}M"


@dataclass
class StatusBar:
    """«Время на телефоне» и иконки статус-бара."""

    time: str = "9:41"
    battery: int = 100
    charging: bool = False
    show_battery_percent: bool = True
    wifi: bool = True
    cellular: bool = True
    cellular_bars: int = 4          # 0..4
    side_margin: float = 30.0


@dataclass
class Channel:
    name: str = "Мой канал"
    subscribers: Any = "125 431 подписчик"
    avatar: Optional[str] = None            # путь к картинке
    avatar_bg: str = "#4A76A8"              # фон, если аватара нет
    avatar_bg2: str = "#7BB0E8"             # второй цвет градиента
    verified: bool = True
    back_text: str = "Чаты"
    header_action: str = "bell"             # bell | bell_off | search | none


@dataclass
class Reaction:
    emoji: str = "👍"
    count: int = 0
    selected: bool = False
    count_text: str = ""                    # если нужно переопределить число


@dataclass
class Post:
    """Сам пост в канале."""

    text: str = ("Привет! Это шаблон поста Telegram-канала 👋\n\n"
                 "Меняется одной строкой: время поста, **реакции** и время на телефоне. "
                 "Работает `разметка`, ссылки вида t.me/telegram и @упоминания.\n\n"
                 "Картинку приложите любую — путь указывается в post.media 📷")
    media: Optional[str] = None             # путь к картинке/видео-кадру
    time: str = "12:34"                     # время поста
    views: int = 12_500                     # просмотры
    views_text: str = ""
    views_format: str = "km"                # km | ru | raw
    show_views: bool = True
    reactions: List[Reaction] = field(default_factory=lambda: [
        Reaction("🔥", 431, True),
        Reaction("❤️", 128),
        Reaction("👍", 64),
    ])
    buttons: List[Any] = field(default_factory=list)   # ["Текст"] или [{"text": "..."}]
    date_chip: str = "10 октября"
    show_date_chip: bool = True
    show_tail: bool = True
    text_size: float = 16.0                 # кегль текста поста, pt
    line_spacing: float = 2.0               # доп. межстрочный интервал, pt
    max_width: float = 0.0                  # 0 = авто
    media_max_width: float = 0.0            # 0 = авто


@dataclass
class BottomBar:
    type: str = "join"                      # join | input | none
    text: str = "Подписаться"
    placeholder: str = "Сообщение"


@dataclass
class Screen:
    device: str = "iphone_15_pro"
    scale: int = 3                          # 1, 2 или 3
    theme: str = "dark"                     # dark | light
    theme_overrides: Dict[str, Any] = field(default_factory=dict)
    background: str = "pattern"             # pattern | flat | gradient
    scroll: float = 0.0                     # сдвинуть контент вверх (имитация скролла)
    output: str = "output/post.png"


@dataclass
class Config:
    screen: Screen = field(default_factory=Screen)
    status: StatusBar = field(default_factory=StatusBar)
    channel: Channel = field(default_factory=Channel)
    post: Post = field(default_factory=Post)
    bottom: BottomBar = field(default_factory=BottomBar)

    # ---------- (де)сериализация ----------
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        data = dict(data or {})
        kwargs: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name in data:
                kwargs[f.name] = _build(f.type if isinstance(f.type, type) else _resolve(f.type), data[f.name])
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)


def _resolve(tp: Any) -> Any:
    """Разбирает строковые аннотации (включён from __future__ import annotations)."""
    if not isinstance(tp, str):
        return tp
    tp = tp.strip()
    m = re.match(r"(?:List|Sequence|Tuple|list|tuple)\[(.+)\]$", tp)
    if m:
        return (list, _resolve(m.group(1)))
    m = re.match(r"Optional\[(.+)\]$", tp)
    if m:
        return _resolve(m.group(1))
    return globals().get(tp, tp)


def _build(tp: Any, value: Any) -> Any:
    if isinstance(tp, tuple) and tp and tp[0] is list:
        return [_build(tp[1], v) for v in value] if isinstance(value, list) else value
    if is_dataclass(tp) and isinstance(value, dict):
        kwargs = {}
        for f in fields(tp):
            if f.name in value:
                kwargs[f.name] = _build(_resolve(f.type), value[f.name])
        return tp(**kwargs)
    return value


def default_config() -> Config:
    return Config()


def reactions_from_pairs(pairs: Sequence[Any]) -> List[Reaction]:
    """Гибкий разбор реакций: ["🔥 431", {"emoji": "🔥", "count": 431}, ["🔥", 431]]."""
    out: List[Reaction] = []
    for item in pairs:
        if isinstance(item, Reaction):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Reaction(**{k: v for k, v in item.items() if k in {f.name for f in fields(Reaction)}}))
        elif isinstance(item, (list, tuple)):
            emoji = str(item[0])
            count = int(item[1]) if len(item) > 1 else 0
            selected = bool(item[2]) if len(item) > 2 else False
            out.append(Reaction(emoji, count, selected))
        elif isinstance(item, str):
            parts = item.strip().split()
            emoji = parts[0] if parts else ""
            count = 0
            if len(parts) > 1:
                digits = "".join(ch for ch in parts[1] if ch.isdigit())
                count = int(digits) if digits else 0
            out.append(Reaction(emoji, count))
    return out
