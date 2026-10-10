"""
Отрисовка цветных эмодзи (Noto Color Emoji) без внешних сервисов.

Почему так сложно: Noto Color Emoji — это шрифт с таблицами CBDT/CBLC
(готовые PNG-картинки вместо векторных контуров). FreeType в Debian собран
без поддержки PNG внутри CBDT, поэтому стандартный путь
`PIL.ImageFont.truetype(...)` / `freetype-py` падает с ошибкой
"unimplemented feature". Здесь CBDT/CBLC разбираются вручную, а PNG
раскодируются через Pillow.

Пайплайн:
  1. текст -> последовательность glyph id (uharfbuzz, чтобы корректно
     склеивать ZWJ-последовательности, скин-тоны и VS16; без uharfbuzz
     работает упрощённый fallback по codepoint);
  2. glyph id -> смещение в CBDT (таблицы CBLC);
  3. PNG из CBDT -> Pillow -> кэш по размеру -> наклейка в итоговое изображение.
"""

from __future__ import annotations

import io
import os
import struct
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

DEFAULT_EMOJI_FONT_CANDIDATES = (
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
)

# Диапазоны кодов, которые считаем «эмодзи» (грубая, но практичная эвристика).
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),  # основной блок эмодзи
    (0x1F1E6, 0x1F1FF),  # региональные индикаторы (флаги)
    (0x2600, 0x27BF),    # разное: символы, dingbats
    (0x2B00, 0x2BFF),    # стрелки/разное
    (0xFE0F, 0xFE0F),    # variation selector-16
    (0x1F3FB, 0x1F3FF),  # скин-тоны
    (0xE0020, 0xE007F),  # тэги флагов
    (0x2049, 0x2049),
    (0x203C, 0x203C),
    (0x2139, 0x2139),
    (0x2194, 0x21AA),
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25FE),
    (0x2934, 0x2935),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3299),
    (0x00A9, 0x00AE),
)
_ZWJ = 0x200D
_VS16 = 0xFE0F


def is_emoji_codepoint(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def split_emoji_runs(text: str) -> List[Tuple[bool, str]]:
    """Разбивает строку на блоки: (эмодзи?, подстрока).

    Эмодзи-блок включает ZWJ-последовательности, скин-тоны, VS16 и keycap-суффиксы,
    чтобы ❤️ и 👩‍💻 рисовались одним глифом, а не набором отдельных символов.
    """
    runs: List[Tuple[bool, str]] = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if is_emoji_codepoint(cp):
            j = i + 1
            while j < n:
                c2 = ord(text[j])
                # продолжение последовательности: эмодзи, VS16, ZWJ, скин-тон, keycap
                if is_emoji_codepoint(c2) or c2 in (_ZWJ, _VS16, 0x20E3):
                    # одиночный пробел между эмодзи — не часть последовательности
                    j += 1
                else:
                    break
            runs.append((True, text[i:j]))
            i = j
        else:
            j = i + 1
            while j < n and not is_emoji_codepoint(ord(text[j])):
                j += 1
            runs.append((False, text[i:j]))
            i = j
    return runs


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


class _Cmap:
    """Минимальный парсер cmap (поддерживаются форматы 4 и 12)."""

    def __init__(self, data: bytes, tables: Dict[str, Tuple[int, int]]):
        self.data = data
        self.tables = tables
        self._fmt4: Optional[Tuple[int, int]] = None   # (subtable_off, segCountX2)
        self._fmt12: Optional[int] = None

        cmap_off = tables["cmap"][0]
        num_tables = _u16(data, cmap_off + 2)
        best: List[Tuple[int, int, int]] = []
        for i in range(num_tables):
            rec = cmap_off + 4 + i * 8
            platform, encoding, offset = struct.unpack_from(">HHI", data, rec)
            sub = cmap_off + offset
            fmt = _u16(data, sub)
            # (3,10)=format12 UCS-4, (3,1)=format4 BMP, (0,x)=Unicode
            score = 0
            if platform == 3 and encoding == 10:
                score = 5
            elif platform == 3 and encoding == 1:
                score = 4
            elif platform == 0:
                score = 2
            else:
                score = 1
            best.append((score, fmt, sub))
        best.sort(reverse=True)
        for _, fmt, sub in best:
            if fmt == 12 and self._fmt12 is None:
                self._fmt12 = sub
            if fmt == 4 and self._fmt4 is None:
                self._fmt4 = (sub, _u16(data, sub + 6))
        self._cache: Dict[str, int] = {}

    def gid(self, text: str) -> int:
        """Ищет glyph id для строки (актуально для одиночных символов)."""
        if text in self._cache:
            return self._cache[text]
        cp = ord(text[0]) if text else 0
        gid = 0
        if self._fmt12 is not None:
            gid = self._lookup12(self._fmt12, cp)
        if not gid and self._fmt4 is not None:
            gid = self._lookup4(*self._fmt4, cp)
        self._cache[text] = gid
        return gid

    def _lookup12(self, sub: int, cp: int) -> int:
        data = self.data
        ngroups = _u32(data, sub + 12)
        lo, hi = 0, ngroups - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            base = sub + 16 + mid * 12
            start, end, start_gid = struct.unpack_from(">III", data, base)
            if cp < start:
                hi = mid - 1
            elif cp > end:
                lo = mid + 1
            else:
                return start_gid + (cp - start)
        return 0

    def _lookup4(self, sub: int, seg_x2: int, cp: int) -> int:
        data = self.data
        seg_count = seg_x2 // 2
        end_base = sub + 14
        start_base = end_base + seg_x2 + 2
        delta_base = start_base + seg_x2
        range_base = delta_base + seg_x2
        for i in range(seg_count):
            end = _u16(data, end_base + i * 2)
            if cp <= end:
                start = _u16(data, start_base + i * 2)
                if cp < start:
                    return 0
                delta = struct.unpack_from(">h", data, delta_base + i * 2)[0]
                ro = _u16(data, range_base + i * 2)
                if ro == 0:
                    return (cp + delta) & 0xFFFF
                addr = range_base + i * 2 + ro + (cp - start) * 2
                gid = _u16(data, addr)
                return (gid + delta) & 0xFFFF if gid else 0
        return 0


class NotoColorEmoji:
    """Читает PNG-глифы напрямую из CBDT/CBLC."""

    def __init__(self, path: str):
        with open(path, "rb") as fh:
            self.data = fh.read()
        self.data_bytes = self.data
        num_tables = _u16(self.data, 4)
        self.tables: Dict[str, Tuple[int, int]] = {}
        for i in range(num_tables):
            off = 12 + 16 * i
            tag = self.data[off:off + 4].decode("latin-1")
            _cks, start, length = struct.unpack_from(">III", self.data, off + 4)
            self.tables[tag] = (start, length)
        self.cmap = _Cmap(self.data, self.tables)
        self.upem = _u16(self.data, self.tables["head"][0] + 18) or 2048
        self._glyph_offsets: Dict[int, int] = {}
        self.ppem = 109.0
        self._parse_cblc()
        self._shape = self._make_shaper()

    # ---------- разбор CBLC ----------
    def _parse_cblc(self) -> None:
        if "CBLC" not in self.tables or "CBDT" not in self.tables:
            raise ValueError("Этот шрифт не содержит CBLC/CBDT (ожидается Noto Color Emoji)")
        cblc = self.tables["CBLC"][0]
        num_sizes = _u32(self.data, cblc + 4)
        if not num_sizes:
            raise ValueError("В шрифте нет strike-ов")
        strike = cblc + 8
        idx_arr_off = _u32(self.data, strike)
        num_subs = _u32(self.data, strike + 8)
        _sg, _eg, ppem_x, ppem_y, _bd, _flags = struct.unpack_from(">HHBBbb", self.data, strike + 40)
        self.ppem = float(ppem_y or ppem_x or 109)
        base = cblc + idx_arr_off
        for i in range(num_subs):
            first, last, add = struct.unpack_from(">HHI", self.data, base + i * 8)
            sub = base + add
            fmt, _img_fmt = struct.unpack_from(">HH", self.data, sub)
            if fmt == 1:
                img_data_off = _u32(self.data, sub + 4)
                for k in range(last - first + 2):
                    off = _u32(self.data, sub + 8 + k * 4)
                    if k <= last - first:
                        self._glyph_offsets[first + k] = img_data_off + off
            elif fmt == 3:
                img_data_off = _u32(self.data, sub + 4)
                for k in range(last - first + 2):
                    off = _u16(self.data, sub + 8 + k * 2)
                    if k <= last - first:
                        self._glyph_offsets[first + k] = img_data_off + off
            elif fmt in (2, 4, 5):
                img_size = _u32(self.data, sub + 4)
                big_off = sub + (12 if fmt in (4, 5) else 8)
                big_metrics = self.data[big_off:big_off + 8]
                for k in range(last - first + 1):
                    self._glyph_offsets[first + k] = (sub, img_size, big_metrics)  # type: ignore[assignment]
                # формат 2/4/5: данные идут последовательно сразу после подтаблицы
                data_start = sub + (12 if fmt in (4, 5) else 8) + (8 if fmt == 5 else 0)
                for k in range(last - first + 1):
                    self._glyph_offsets[first + k] = data_start + k * img_size
            else:
                # редкие форматы — просто пропускаем (на практике не встречаются)
                continue

    # ---------- формирование последовательности глифов ----------
    def _make_shaper(self):
        try:
            import uharfbuzz as hb  # type: ignore
        except Exception:
            return None
        blob = self.data_bytes

        def shape(text: str):
            face = hb.Face(blob)
            font = hb.Font(face)
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            hb.shape(font, buf)
            infos, positions = buf.glyph_infos, buf.glyph_positions
            out = []
            for info, pos in zip(infos, positions):
                out.append((int(info.codepoint), int(pos.x_advance)))
            return out

        return shape

    def glyphs_for(self, text: str) -> List[Tuple[int, int]]:
        """Возвращает [(glyph_id, advance_in_font_units_or_px)]."""
        if self._shape is not None:
            try:
                gids = self._shape(text)
                if gids:
                    return gids
            except Exception:
                pass
        # fallback: по одному символу, без ZWJ/VS16
        out = []
        for ch in text:
            if ord(ch) in (_ZWJ, _VS16):
                continue
            gid = self.cmap.gid(ch)
            if gid:
                out.append((gid, 0))
        return out

    # ---------- метрики ----------
    def _parse_hmtx(self) -> None:
        self._advances: List[int] = []
        self._last_advance = 0
        if "hmtx" not in self.tables or "hhea" not in self.tables:
            return
        hhea = self.tables["hhea"][0]
        count = _u16(self.data, hhea + 34)
        hmtx = self.tables["hmtx"][0]
        for i in range(count):
            self._advances.append(_u16(self.data, hmtx + i * 4))
        if self._advances:
            self._last_advance = self._advances[-1]
        extra = (self.tables["hmtx"][1] - count * 4) // 2
        self._advances += [self._last_advance] * max(0, extra)

    def advance_units(self, gid: int) -> int:
        if not hasattr(self, "_advances"):
            self._parse_hmtx()
        if not self._advances:
            return self.upem
        if gid < len(self._advances):
            return self._advances[gid]
        return self._last_advance or self.upem

    # ---------- растр ----------
    @lru_cache(maxsize=4096)
    def _glyph_image(self, gid: int):
        """Возвращает (картинка, bearingX, bearingY, height) в нативном размере strike-а."""
        off = self._glyph_offsets.get(gid)
        if off is None:
            return None
        cbdt = self.tables["CBDT"][0]
        p = cbdt + off
        height, width, bx, by, _adv = struct.unpack_from(">BBbbB", self.data, p)
        start = p + 5
        head = self.data[start:start + 16]
        png_at = head.find(b"\x89PNG")
        if png_at < 0:
            return None
        start += png_at
        try:
            img = Image.open(io.BytesIO(self.data[start:]))
            img.load()
        except Exception:
            return None
        return img.convert("RGBA"), bx, by, height

    def render(self, text: str, size_px: float):
        """Рисует эмодзи-последовательность.

        Возвращает (RGBA-изображение, смещение базовой линии от верха картинки)
        либо None, если глифы найти не удалось.
        """
        target = max(4.0, float(size_px))
        glyphs = self.glyphs_for(text)
        if not glyphs:
            return None

        scale = target / self.ppem       # нативный strike -> нужный кегль
        unit = target / self.upem        # font units -> px

        placed = []
        x = 0.0
        above = 0.0
        below = 0.0
        for gid, adv in glyphs:
            meta = self._glyph_image(gid)
            if meta is None:
                continue
            im, bx, by, h = meta
            w = max(1, int(round(im.width * scale)))
            h_px = max(1, int(round(h * scale)))
            img = im.resize((w, h_px), Image.LANCZOS)
            top_above = by * scale                 # насколько глиф выступает выше базовой линии
            bottom_below = (h - by) * scale        # насколько ниже базовой линии
            above = max(above, top_above)
            below = max(below, bottom_below)
            placed.append((img, x + bx * scale, top_above))
            advance_px = (adv or self.advance_units(gid)) * unit
            x += advance_px
        if not placed:
            return None

        baseline = int(round(above))
        canvas_h = max(1, baseline + int(round(below)))
        canvas_w = max(1, int(round(x)))
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        for img, px, top_above in placed:
            canvas.alpha_composite(img, (int(round(px)), baseline - int(round(top_above))))
        return canvas, baseline

@lru_cache(maxsize=8)
def _load(path: str) -> Optional[NotoColorEmoji]:
    try:
        return NotoColorEmoji(path)
    except Exception:
        return None


def find_emoji_font(extra: Sequence[str] = ()) -> Optional[str]:
    for p in list(extra) + list(DEFAULT_EMOJI_FONT_CANDIDATES):
        if p and os.path.exists(p):
            return p
    return None


class EmojiRun:
    """Готовый к наклейке эмодзи + его положение относительно базовой линии."""

    __slots__ = ("image", "baseline_y", "width", "height")

    def __init__(self, image: Image.Image, baseline_y: int):
        self.image = image
        self.baseline_y = baseline_y
        self.width = image.width
        self.height = image.height


class EmojiRenderer:
    """Кэширующий рендерер эмодзи с деградацией до монохромного шрифта."""

    def __init__(self, font_path: Optional[str] = None, fallback_font_path: Optional[str] = None):
        self.font_path = font_path or find_emoji_font()
        self._impl = _load(self.font_path) if self.font_path else None
        self.fallback_font_path = fallback_font_path
        self._cache: Dict[Tuple[str, int], Optional[EmojiRun]] = {}

    @property
    def available(self) -> bool:
        return self._impl is not None

    def get(self, text: str, size_px: float) -> Optional[EmojiRun]:
        """Возвращает EmojiRun для последовательности эмодзи."""
        key = (text, int(round(size_px)))
        if key in self._cache:
            return self._cache[key]
        run = None
        if self._impl is not None:
            try:
                res = self._impl.render(text, size_px)
                if res is not None:
                    img, baseline = res
                    run = EmojiRun(img, baseline)
            except Exception:
                run = None
        if run is None and self.fallback_font_path:
            run = self._mono(text, size_px)
        self._cache[key] = run
        return run

    def _mono(self, text: str, size_px: float) -> Optional[Image.Image]:
        from PIL import ImageDraw, ImageFont

        try:
            font = ImageFont.truetype(self.fallback_font_path, int(size_px))
        except Exception:
            return None
        box = font.getbbox(text)
        canvas = Image.new("RGBA", (max(1, box[2] - box[0]), max(1, box[3] - box[1])), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((-box[0], -box[1]), text, font=font, fill=(255, 255, 255, 255))
        return EmojiRun(canvas, canvas.height)
