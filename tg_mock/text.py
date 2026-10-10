"""
Вёрстка текста Telegram-сообщения: лёгкая разметка, переносы по словам,
смешанный вывод обычного текста и цветных эмодзи.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from . import emoji as emoji_mod

# ---------- разметка ----------
_TOKEN_RE = re.compile(
    r"(\*\*|__)"                      # жирный
    r"|(\*|_)"                        # курсив
    r"|(`+)"                          # моноширинный
    r"|(\|\|)"                        # спойлер
    r"|(\[[^\]\n]+\]\([^)\n]+\))"     # [текст](ссылка)
    r"|(https?://[^\s<>\]]+"          # ссылка
    r"|www\.[^\s<>\]]+"
    r"|t\.me/[^\s<>\]]+"
    r"|@[A-Za-z0-9_]{3,}"
    r"|#[A-Za-zА-Яа-яЁё0-9_]{2,})",
    re.IGNORECASE,
)

_URL_IN_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")

STYLE_PLAIN = "plain"
STYLE_BOLD = "bold"
STYLE_ITALIC = "italic"
STYLE_MONO = "mono"
STYLE_LINK = "link"
STYLE_SPOILER = "spoiler"
STYLE_BREAK = "break"          # принудительный перенос (символ \n)


@dataclass
class Atom:
    """Неделимый кусочек текста с одним стилем."""

    text: str
    style: str = STYLE_PLAIN
    url: str = ""


@dataclass
class Line:
    atoms: List[Atom] = field(default_factory=list)
    width: float = 0.0


def parse_markup(text: str) -> List[Atom]:
    """Разбирает Telegram-подобную разметку в список атомов.

    Символы перевода строки превращаются в атомы со стилем STYLE_BREAK:
    иначе Pillow сам нарисует вторую строку ниже, и текст «поедет».
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    atoms: List[Atom] = []
    stack: List[str] = []          # активные стили
    buf: List[str] = []

    def flush(style: Optional[str] = None, url: str = ""):
        chunk = "".join(buf)
        buf.clear()
        if not chunk:
            return
        st = style or (stack[-1] if stack else STYLE_PLAIN)
        segments = chunk.split("\n")
        for i, segment in enumerate(segments):
            if i:
                atoms.append(Atom("\n", STYLE_BREAK))
            for is_emoji, piece in emoji_mod.split_emoji_runs(segment):
                if not piece:
                    continue
                atoms.append(Atom(piece, st, url if not is_emoji else ""))

    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos) or _TOKEN_RE.search(text, pos)
        if not m:
            buf.append(text[pos:])
            break
        if m.start() > pos:
            buf.append(text[pos:m.start()])
        tok = m.group(0)

        if tok in ("**", "__"):
            flush()
            if STYLE_BOLD in stack:
                stack.remove(STYLE_BOLD)
            else:
                stack.append(STYLE_BOLD)
        elif tok in ("*", "_"):
            flush()
            if STYLE_ITALIC in stack:
                stack.remove(STYLE_ITALIC)
            else:
                stack.append(STYLE_ITALIC)
        elif tok.startswith("`"):
            flush()
            if STYLE_MONO in stack:
                stack.remove(STYLE_MONO)
            else:
                stack.append(STYLE_MONO)
        elif tok == "||":
            flush()
            if STYLE_SPOILER in stack:
                stack.remove(STYLE_SPOILER)
            else:
                stack.append(STYLE_SPOILER)
        elif tok.startswith("["):
            lm = _URL_IN_LINK_RE.match(tok)
            flush()
            if lm:
                atoms.append(Atom(lm.group(1), STYLE_LINK, lm.group(2)))
            else:
                atoms.append(Atom(tok))
        else:
            flush()
            atoms.append(Atom(tok, STYLE_LINK, tok))

        pos = m.end()

    flush()
    return atoms


# ---------- метрики и переносы ----------
class TextStyle:
    """Как рисовать каждый стиль: вес шрифта, цвет, подложка."""

    def __init__(self, colors: Dict[str, Tuple[int, int, int, int]], mono_font=None):
        self.colors = colors
        self.mono_font = mono_font

    def weight(self, base_weight: int, style: str) -> int:
        if style == STYLE_BOLD:
            return max(base_weight, 600)
        return base_weight

    def color(self, style: str) -> Tuple[int, int, int, int]:
        return self.colors.get(style, self.colors[STYLE_PLAIN])


def _is_space(s: str) -> bool:
    return s.strip() == "" and s != ""


def _split_words(atom: Atom) -> List[Atom]:
    """Режет атом на слова, пробелы сохраняются слева от следующего слова."""
    if atom.style == STYLE_BREAK or _is_space(atom.text):
        return [atom]
    out: List[Atom] = []
    parts = re.split(r"(?<= )", atom.text)
    pending = ""
    for part in parts:
        if part.endswith(" ") and part.strip():
            out.append(Atom(part[:-1], atom.style, atom.url))
            out.append(Atom(" ", atom.style, atom.url))
        elif part == " ":
            out.append(Atom(" ", atom.style, atom.url))
        else:
            out.append(Atom(part, atom.style, atom.url))
    return out or [atom]


def _measure(atom: Atom, fonts, style: TextStyle, base_weight: int, size_px: float) -> float:
    if not atom.text or atom.style == STYLE_BREAK:
        return 0.0
    runs = emoji_mod.split_emoji_runs(atom.text)
    total = 0.0
    for is_emoji, piece in runs:
        if not piece:
            continue
        if is_emoji:
            run = fonts.emoji.get(piece, size_px)
            total += run.width if run else fonts.text_width(piece, base_weight, size_px)
        else:
            w = style.weight(base_weight, atom.style)
            total += fonts.text_width(piece, w, size_px)
    return total


def wrap_atoms(
    atoms: Sequence[Atom],
    fonts,
    style: TextStyle,
    base_weight: int,
    size_px: float,
    max_width: float,
) -> List[Line]:
    """Жадный перенос по словам с учётом ширины эмодзи."""
    words: List[Atom] = []
    for atom in atoms:
        words.extend(_split_words(atom))

    lines: List[Line] = []
    cur = Line()
    for word in words:
        if word.style == STYLE_BREAK:
            while cur.atoms and cur.atoms[-1].text == " ":
                cur.atoms.pop()
            lines.append(cur)
            cur = Line()
            continue
        w = _measure(word, fonts, style, base_weight, size_px)
        if cur.atoms and cur.width + w > max_width:
            if _is_space(word.text) or word.text == " ":
                continue
            trailing = cur.atoms[-1]
            if trailing.text == " ":
                cur.atoms.pop()
            lines.append(cur)
            cur = Line()
            if w <= max_width:
                cur.atoms.append(word)
                cur.width = w
                continue
        if w > max_width and not _is_space(word.text):
            # слишком длинное «слово» — режем по символам
            if cur.width:
                lines.append(cur)
                cur = Line()
            chunk = ""
            chunk_w = 0.0
            for ch in word.text:
                cw = _measure(Atom(ch, word.style, word.url), fonts, style, base_weight, size_px)
                if chunk and chunk_w + cw > max_width:
                    cur.atoms.append(Atom(chunk, word.style, word.url))
                    cur.width = chunk_w
                    lines.append(cur)
                    cur = Line()
                    chunk, chunk_w = "", 0.0
                chunk += ch
                chunk_w += cw
            if chunk:
                cur.atoms.append(Atom(chunk, word.style, word.url))
                cur.width = chunk_w
            continue
        cur.atoms.append(word)
        cur.width += w
    if cur.atoms or not lines:
        lines.append(cur)
    # убираем висячие пробелы в конце строк (пустые строки-абзацы сохраняем)
    for line in lines:
        while line.atoms and line.atoms[-1].text == " ":
            line.atoms.pop()
    return lines or [Line([Atom("")], 0.0)]


def line_width(line: Line, fonts, style: TextStyle, base_weight: int, size_px: float) -> float:
    return sum(_measure(a, fonts, style, base_weight, size_px) for a in line.atoms)


# ---------- отрисовка ----------
def draw_line(
    img: Image.Image,
    line: Line,
    x: float,
    baseline_y: float,
    fonts,
    style: TextStyle,
    base_weight: int,
    size_px: float,
    underline_links: bool = False,
) -> None:
    d = ImageDraw.Draw(img)
    cx = float(x)
    for atom in line.atoms:
        if not atom.text or atom.style == STYLE_BREAK:
            continue
        runs = emoji_mod.split_emoji_runs(atom.text.replace("\n", ""))
        for is_emoji, piece in runs:
            if not piece:
                continue
            if is_emoji:
                run = fonts.emoji.get(piece, size_px)
                if run is not None:
                    img.alpha_composite(run.image, (int(round(cx)), int(round(baseline_y - run.baseline_y))))
                    cx += run.width
                    continue
            weight = style.weight(base_weight, atom.style)
            font = fonts.get(weight, size_px)
            color = style.color(atom.style)
            if atom.style == STYLE_MONO:
                tw = fonts.text_width(piece, weight, size_px)
                d.rounded_rectangle(
                    [cx - size_px * 0.08, baseline_y - size_px * 0.86, cx + tw + size_px * 0.08, baseline_y + size_px * 0.28],
                    radius=size_px * 0.22,
                    fill=style.colors.get("mono_bg", (128, 128, 128, 60)),
                )
            if atom.style == STYLE_SPOILER:
                tw = fonts.text_width(piece, weight, size_px)
                d.rounded_rectangle(
                    [cx, baseline_y - size_px * 0.82, cx + tw, baseline_y + size_px * 0.22],
                    radius=size_px * 0.18,
                    fill=style.colors.get("spoiler_bg", (128, 128, 128, 110)),
                )
                cx += tw
                continue
            d.text((cx, baseline_y), piece, font=font, fill=color, anchor="ls")
            if underline_links and atom.style == STYLE_LINK:
                tw = fonts.text_width(piece, weight, size_px)
                d.line(
                    [cx, baseline_y + size_px * 0.14, cx + tw, baseline_y + size_px * 0.14],
                    fill=color,
                    width=max(1, int(round(size_px * 0.05))),
                )
            cx += fonts.text_width(piece, weight, size_px)


def layout(
    text: str,
    fonts,
    style: TextStyle,
    base_weight: int,
    size_px: float,
    max_width: float,
    line_spacing: float = 0.0,
) -> Tuple[List[Line], float, float, float]:
    """Возвращает (строки, высота блока, ascent, межстрочный шаг)."""
    atoms = parse_markup(text)
    lines = wrap_atoms(atoms, fonts, style, base_weight, size_px, max_width)
    ascent, descent = fonts.ascent_descent(base_weight, size_px)
    step = ascent + descent + line_spacing
    height = step * (len(lines) - 1) + ascent + descent
    return lines, height, float(ascent), step


def draw_block(
    img: Image.Image,
    lines: Sequence[Line],
    x: float,
    top_y: float,
    ascent: float,
    step: float,
    fonts,
    style: TextStyle,
    base_weight: int,
    size_px: float,
    align: str = "left",
    block_width: Optional[float] = None,
    underline_links: bool = False,
) -> float:
    """Рисует блок текста. Возвращает нижнюю границу (y)."""
    baseline = top_y + ascent
    for line in lines:
        lw = line_width(line, fonts, style, base_weight, size_px)
        if align == "right" and block_width:
            lx = x + block_width - lw
        elif align == "center" and block_width:
            lx = x + (block_width - lw) / 2
        else:
            lx = x
        draw_line(img, line, lx, baseline, fonts, style, base_weight, size_px, underline_links)
        baseline += step
    return top_y + step * (len(lines) - 1) + ascent + (fonts.ascent_descent(base_weight, size_px)[1])


def text_height(
    text: str,
    fonts,
    style: TextStyle,
    base_weight: int,
    size_px: float,
    max_width: float,
    line_spacing: float = 0.0,
) -> float:
    lines, height, _a, _s = layout(text, fonts, style, base_weight, size_px, max_width, line_spacing)
    return height
