"""
Рендерер экрана: статус-бар iPhone, шапка канала, пост (текст/фото),
реакции, просмотры, нижняя панель.
"""

from __future__ import annotations

import math
import os
import random
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import text as text_mod
from .config import Config, Reaction, format_subscribers, format_views, plural_ru
from .fonts import FontBook
from .theme import Device, Theme, get_device, get_theme

SS = 4  # коэффициент суперсэмплинга для гладких масок


# ============================== вспомогательное ==============================
def _bezier(p0, p1, p2, p3, steps: int = 36):
    out = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]
        out.append((x, y))
    return out


def _blend(dst: Image.Image, color, box=None) -> None:
    """Заливка с учетом альфы (ImageDraw заменяет пиксели, а не смешивает)."""
    if box is None:
        box = (0, 0, dst.width, dst.height)
    layer = Image.new("RGBA", dst.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(box, fill=color)
    dst.alpha_composite(layer)


class Renderer:
    """Собирает скриншот поста Telegram-канала в стиле iOS."""

    # геометрия (в пунктах)
    BUBBLE_LEFT = 8.0
    BUBBLE_MAX_RATIO = 0.76
    MEDIA_MAX_RATIO = 0.962
    BUBBLE_RADIUS = 16.0
    BUBBLE_PAD_X = 9.0
    BUBBLE_PAD_TOP = 6.0
    BUBBLE_PAD_BOTTOM = 6.0
    BUBBLE_INSET_LEFT = 7.0
    TEXT_SIZE = 16.0
    TEXT_LINE_SPACING = 2.0
    META_SIZE = 12.0
    REACTION_H = 26.0
    REACTION_GAP = 4.0
    REACTION_EMOJI = 13.0
    CHIP_H = 24.0
    NAV_AVATAR = 32.0
    BOTTOM_PANEL_H = 50.0
    BUTTON_H = 40.0

    def __init__(self, config: Config, fonts: Optional[FontBook] = None, base_dir: Optional[str] = None):
        self.cfg = config
        self.k = float(config.screen.scale or 3)
        self.device: Device = get_device(config.screen.device)
        self.theme: Theme = get_theme(config.screen.theme, config.screen.theme_overrides)
        self.fonts = fonts or FontBook()
        self.base_dir = base_dir or os.getcwd()
        self.W = int(round(self.device.width * self.k))
        self.H = int(round(self.device.height * self.k))
        self._avatar_cache: Dict[Tuple[str, int], Image.Image] = {}
        self.boxes: List[Tuple[str, Tuple[float, float, float, float]]] = []  # для автотестов

    # ---------- утилиты ----------
    def p(self, v: float) -> float:
        """Пункты -> пиксели."""
        return float(v) * self.k

    def resolve(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        if os.path.isabs(path) and os.path.exists(path):
            return path
        candidates = [
            os.path.join(self.base_dir, path),
            os.path.join(os.path.dirname(self.base_dir), path) if self.base_dir else path,
            path,
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    # ============================== основной цикл ==============================
    def render(self) -> Image.Image:
        img = Image.new("RGBA", (self.W, self.H), self.theme.chat_bg)
        self._background(img)

        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        chat_top = int(round(self.p(self.device.status_h + self.device.nav_h)))
        panel_top = self.H - int(round(self.p(self.device.bottom_safe + self.BOTTOM_PANEL_H)))
        if self.cfg.bottom.type == "none":
            panel_top = self.H
        self._chat(layer, top_px=chat_top)
        region = layer.crop((0, 0, self.W, panel_top))
        img.alpha_composite(region, (0, 0))

        self._status_bar(img)
        self._cutout(img)
        self._nav_bar(img)
        if self.cfg.bottom.type != "none":
            self._bottom_bar(img)
        self._home_indicator(img)
        return img.convert("RGB")

    # ============================== фон ==============================
    def _background(self, img: Image.Image) -> None:
        mode = (self.cfg.screen.background or "pattern").lower()
        if mode == "flat":
            return
        overlay = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        if mode == "gradient":
            for y in range(self.H):
                t = y / max(1, self.H - 1)
                a, b = self.theme.chat_bg, self.theme.chat_bg_2
                color = (
                    int(a[0] + (b[0] - a[0]) * t),
                    int(a[1] + (b[1] - a[1]) * t),
                    int(a[2] + (b[2] - a[2]) * t),
                    255,
                )
                d.line([(0, y), (self.W, y)], fill=color)
            img.alpha_composite(overlay)
            return

        # «pattern»: едва заметный повторяющийся узор (имитация фона Telegram)
        rnd = random.Random(20241010)
        step = int(self.p(58))
        alpha = 14
        base = self.theme.text
        for gy in range(-1, self.H // step + 2):
            for gx in range(-1, self.W // step + 2):
                kind = rnd.randint(0, 4)
                cx = gx * step + int(step * (0.2 + 0.6 * rnd.random()))
                cy = gy * step + int(step * (0.2 + 0.6 * rnd.random()))
                r = int(self.p(5 + rnd.random() * 9))
                col = (base[0], base[1], base[2], alpha)
                if kind == 0:
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=max(1, int(self.k * 0.5)))
                elif kind == 1:
                    d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=int(r * 0.4),
                                        outline=col, width=max(1, int(self.k * 0.5)))
                elif kind == 2:
                    d.line([cx - r, cy + r, cx, cy - r, cx + r, cy + r], fill=col,
                           width=max(1, int(self.k * 0.5)), joint="curve")
                elif kind == 3:
                    d.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2], fill=col)
                else:
                    d.arc([cx - r, cy - r, cx + r, cy + r], start=20, end=250, fill=col,
                          width=max(1, int(self.k * 0.5)))
        img.alpha_composite(overlay)

    # ============================== статус-бар ==============================
    def _status_bar(self, img: Image.Image) -> None:
        th = self.theme
        cfg = self.cfg.status
        center_y = self.p(self.device.status_h * 0.55)

        # время
        f = self.fonts.get(600, self.p(17))
        d = ImageDraw.Draw(img)
        d.text((self.p(cfg.side_margin), center_y), cfg.time, font=f, fill=th.status_bar_text, anchor="lm")

        # правый блок: соты -> Wi-Fi -> батарея
        right = self.W - self.p(22)
        batt_w = self.p(27.3)
        right = self._battery(img, right - batt_w, center_y, batt_w)
        right -= self.p(7)
        if cfg.wifi:
            right = self._wifi(img, right - self.p(17), center_y, self.p(17))
            right -= self.p(6)
        if cfg.cellular:
            self._cellular(img, right - self.p(18), center_y, self.p(18))

    def _cellular(self, img: Image.Image, x: float, cy: float, w: float) -> float:
        d = ImageDraw.Draw(img)
        color = self.theme.icon
        bars = 4
        total = self.cfg.status.cellular_bars
        bw = w / (bars * 1.62)
        gap = (w - bars * bw) / (bars - 1)
        heights = [0.36, 0.55, 0.75, 1.0]
        for i in range(bars):
            h = w * 0.62 * heights[i]
            bx = x + i * (bw + gap)
            if i < total:
                d.rounded_rectangle([bx, cy + w * 0.31 - h, bx + bw, cy + w * 0.31],
                                    radius=max(1, bw * 0.35), fill=color)
            else:
                d.rounded_rectangle([bx, cy + w * 0.31 - h, bx + bw, cy + w * 0.31],
                                    radius=max(1, bw * 0.35), fill=self.theme.icon_secondary)
        return x

    def _wifi(self, img: Image.Image, x: float, cy: float, w: float) -> float:
        d = ImageDraw.Draw(img)
        color = self.theme.icon
        cx = x + w / 2
        bottom = cy + w * 0.30
        dot_r = w * 0.085
        d.ellipse([cx - dot_r, bottom - dot_r * 2.2, cx + dot_r, bottom - dot_r * 0.2], fill=color)
        for i, frac in enumerate((0.36, 0.62, 0.9)):
            r = w * frac / 2
            width = max(1, int(round(w * 0.085)))
            box = [cx - r, bottom - r * 1.9, cx + r, bottom + r * 0.1]
            d.arc(box, start=200, end=340, fill=color, width=width)
        return x

    def _battery(self, img: Image.Image, x: float, cy: float, w: float) -> float:
        d = ImageDraw.Draw(img)
        th = self.theme
        cfg = self.cfg.status
        h = self.p(13)
        y = cy - h / 2
        stroke = max(1, int(round(self.p(1.2))))
        outline = (th.icon[0], th.icon[1], th.icon[2], 110)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        # «носик» батареи
        nub_w = self.p(1.6)
        od.rounded_rectangle([x + w + self.p(1.2), cy - self.p(2.4), x + w + self.p(1.2) + nub_w, cy + self.p(2.4)],
                             radius=nub_w / 2, fill=outline)
        # корпус
        od.rounded_rectangle([x, y, x + w, y + h], radius=self.p(4.4), outline=outline, width=stroke)
        level = max(0.0, min(1.0, (cfg.battery or 0) / 100.0))
        inset = self.p(2.2)
        fill_w = (w - inset * 2) * level
        if fill_w > self.p(1):
            od.rounded_rectangle([x + inset, y + inset, x + inset + fill_w, y + h - inset],
                                 radius=self.p(2.2), fill=th.icon)
        if cfg.charging:
            self._bolt(od, x + w / 2, cy, h * 0.62, th.chat_bg if level > 0.45 else th.icon)
        elif cfg.show_battery_percent:
            f = self.fonts.get(600, self.p(11))
            label = f"{int(cfg.battery)}"
            label_w = self.fonts.text_width(label, 600, self.p(11))
            center = x + w / 2
            # цифры контрастны заливке: тёмные по белому, белые по пустому
            over_fill = center - label_w / 2 < x + inset + fill_w
            od.text((center, cy), label, font=f,
                    fill=th.chat_bg if over_fill else th.icon, anchor="mm")
        img.alpha_composite(overlay)
        return x

    @staticmethod
    def _bolt(d: ImageDraw.ImageDraw, cx: float, cy: float, h: float, color) -> None:
        pts = [
            (cx + h * 0.14, cy - h * 0.52),
            (cx - h * 0.24, cy + h * 0.06),
            (cx + h * 0.02, cy + h * 0.06),
            (cx - h * 0.12, cy + h * 0.54),
            (cx + h * 0.26, cy - h * 0.06),
            (cx - h * 0.02, cy - h * 0.06),
        ]
        d.polygon(pts, fill=color)

    # ============================== вырез / «остров» ==============================
    def _cutout(self, img: Image.Image) -> None:
        dev = self.device
        d = ImageDraw.Draw(img)
        black = (0, 0, 0, 255)
        if dev.style == "island" and dev.cutout_w:
            w, h = self.p(dev.cutout_w), self.p(dev.cutout_h)
            x = (self.W - w) / 2
            y = self.p(dev.cutout_top)
            d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=black)
            # объектив камеры
            r = h * 0.30
            cx = x + w - h * 0.62
            cy = y + h / 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(14, 16, 20, 255))
            d.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], fill=(30, 38, 52, 255))
        elif dev.style == "notch" and dev.cutout_w:
            w, h = self.p(dev.cutout_w), self.p(dev.cutout_h)
            x = (self.W - w) / 2
            d.rectangle([x, 0, x + w, h * 0.55], fill=black)
            d.rounded_rectangle([x, 0, x + w, h], radius=self.p(16), fill=black)
            d.rectangle([x, 0, x + w, h * 0.6], fill=black)

    # ============================== шапка канала ==============================
    def _nav_bar(self, img: Image.Image) -> None:
        th = self.theme
        dev = self.device
        top = self.p(dev.status_h)
        h = self.p(dev.nav_h)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        panel = (th.panel_bg[0], th.panel_bg[1], th.panel_bg[2], 235)
        od.rectangle([0, top, self.W, top + h], fill=panel)
        od.line([0, top + h - 1, self.W, top + h - 1], fill=th.separator, width=max(1, int(self.k / 3)))
        img.alpha_composite(overlay)

        d = ImageDraw.Draw(img)
        cy = top + h / 2

        # слева: «< Чаты»
        back = self.cfg.channel.back_text
        f_back = self.fonts.get(400, self.p(17))
        bx = self.p(11)
        self._chevron_left(d, bx, cy, self.p(17) * 0.62, th.accent)
        tx = bx + self.p(11)
        if back:
            d.text((tx, cy), back, font=f_back, fill=th.accent, anchor="lm")
            tx += self.fonts.text_width(back, 400, self.p(17))
        left_limit = tx + self.p(8)

        # справа: иконка
        right_icon = self.cfg.channel.header_action
        icon_x = self.W - self.p(30)
        right_limit = icon_x - self.p(18)
        if right_icon in ("bell", "bell_off"):
            self._bell(d, icon_x, cy, self.p(22), th.accent, muted=(right_icon == "bell_off"))
        elif right_icon == "search":
            self._search(d, icon_x, cy, self.p(20), th.accent)
        elif right_icon == "dots":
            self._dots(d, icon_x, cy, self.p(20), th.accent)
        else:
            right_limit = self.W - self.p(8)

        # по центру: аватар + название + подписчики
        ch = self.cfg.channel
        name_f = self.fonts.get(600, self.p(16))
        sub_f = self.fonts.get(400, self.p(13))
        subs = format_subscribers(ch.subscribers)
        av = self.p(self.NAV_AVATAR)
        gap = self.p(8)
        sub_w = self.fonts.text_width(subs, 400, self.p(13))
        verified_w = (av * 0.42 + self.p(4)) if ch.verified else 0
        avail_name = max(self.p(40), min(right_limit, self.W - left_limit) - left_limit - av - gap - verified_w)
        name = self._ellipsize(ch.name, name_f, avail_name)
        name_w = self.fonts.text_width(name, 600, self.p(16))
        block_w = av + gap + max(name_w + verified_w, sub_w)
        bx0 = max(left_limit, (self.W - block_w) / 2)
        bx0 = min(bx0, right_limit - block_w)
        bx0 = max(bx0, left_limit)

        avatar = self._avatar(int(round(av)))
        img.alpha_composite(avatar, (int(round(bx0)), int(round(cy - av / 2))))
        tx0 = bx0 + av + gap
        d.text((tx0, cy - self.p(9)), name, font=name_f, fill=th.text, anchor="ls")
        if ch.verified:
            self._verified(img, tx0 + name_w + self.p(2) + av * 0.21, cy - self.p(9) - self.p(5), av * 0.42)
        d.text((tx0, cy + self.p(9)), subs, font=sub_f, fill=th.text_secondary, anchor="ls")

    def _ellipsize(self, text: str, font, max_w: float) -> str:
        if self.fonts.text_width(text, 600, self.p(16)) <= max_w:
            return text
        s = text
        while s and self.fonts.text_width(s + "…", 600, self.p(16)) > max_w:
            s = s[:-1]
        return (s + "…") if s else "…"

    def _verified(self, img: Image.Image, cx: float, cy: float, size: float) -> None:
        th = self.theme
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        d.ellipse([cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2], fill=th.accent)
        w = size * 0.5
        pts = [
            (cx - w * 0.52, cy + size * 0.01),
            (cx - w * 0.16, cy + w * 0.38),
            (cx + w * 0.56, cy - w * 0.36),
            (cx + w * 0.56, cy - w * 0.06),
            (cx - w * 0.16, cy + w * 0.92),
            (cx - w * 0.52, cy + w * 0.30),
        ]
        d.polygon(pts, fill=th.accent_contrast)
        img.alpha_composite(overlay)

    # ============================== аватар ==============================
    def _avatar(self, size_px: int) -> Image.Image:
        key = (str(self.cfg.channel.avatar), size_px)
        if key in self._avatar_cache:
            return self._avatar_cache[key]
        path = self.resolve(self.cfg.channel.avatar)
        ss = SS
        mask = Image.new("L", (size_px * ss, size_px * ss), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size_px * ss - 1, size_px * ss - 1], fill=255)
        mask = mask.resize((size_px, size_px), Image.LANCZOS)

        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        if path:
            try:
                av = Image.open(path).convert("RGBA")
                side = min(av.width, av.height)
                av = av.crop(((av.width - side) // 2, (av.height - side) // 2,
                              (av.width - side) // 2 + side, (av.height - side) // 2 + side))
                av = av.resize((size_px, size_px), Image.LANCZOS)
                img.alpha_composite(av)
            except Exception:
                path = None
        if not path:
            self._gradient_avatar(img, size_px)
        img.putalpha(mask)
        self._avatar_cache[key] = img
        return img

    def _gradient_avatar(self, img: Image.Image, size: int) -> None:
        from .theme import hex_rgba

        c1 = hex_rgba(self.cfg.channel.avatar_bg)
        c2 = hex_rgba(self.cfg.channel.avatar_bg2)
        px = img.load()
        for y in range(size):
            t = y / max(1, size - 1)
            color = (int(c1[0] + (c2[0] - c1[0]) * t),
                     int(c1[1] + (c2[1] - c1[1]) * t),
                     int(c1[2] + (c2[2] - c1[2]) * t), 255)
            for x in range(size):
                px[x, y] = color
        initials = "".join(w[0] for w in str(self.cfg.channel.name).split()[:2]).upper()
        if initials:
            d = ImageDraw.Draw(img)
            f = self.fonts.get(600, size * 0.40)
            d.text((size / 2, size / 2), initials, font=f, fill=(255, 255, 255, 255), anchor="mm")

    # ============================== содержимое чата ==============================
    def _chat(self, layer: Image.Image, top_px: int) -> None:
        th = self.theme
        y = top_px + self.p(12) - self.p(self.cfg.screen.scroll)

        # плашка с датой
        if self.cfg.post.show_date_chip and self.cfg.post.date_chip:
            chip_text = str(self.cfg.post.date_chip)
            f = self.fonts.get(500, self.p(13))
            tw = self.fonts.text_width(chip_text, 500, self.p(13))
            w = tw + self.p(22)
            h = self.p(self.CHIP_H)
            x = (self.W - w) / 2
            overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=th.chip_bg)
            layer.alpha_composite(overlay)
            d = ImageDraw.Draw(layer)
            d.text((self.W / 2, y + h / 2), chip_text, font=f, fill=th.chip_text, anchor="mm")
            y += h + self.p(12)

        y, bubble_w = self._post(layer, y)

        # инлайн-кнопки (по ширине пузыря)
        if self.cfg.post.buttons:
            y += self.p(6)
            y = self._buttons(layer, y, bubble_w)

    def _post(self, layer: Image.Image, top: float) -> float:
        th = self.theme
        post = self.cfg.post
        style = text_mod.TextStyle(th.style_colors())

        max_text_w = post.max_width or (self.device.width * self.BUBBLE_MAX_RATIO)
        max_media_w = post.media_max_width or (self.device.width * self.MEDIA_MAX_RATIO)
        bubble_left = self.BUBBLE_LEFT
        inner_pad = self.BUBBLE_PAD_X
        max_inner = max_text_w - inner_pad * 2

        media_img: Optional[Image.Image] = None
        media_w = media_h = 0.0
        if post.media:
            path = self.resolve(post.media)
            if path:
                try:
                    media_img = Image.open(path).convert("RGBA")
                except Exception:
                    media_img = None
        if media_img is not None:
            aspect = media_img.width / max(1, media_img.height)
            media_w = min(max_media_w, self.device.width - bubble_left * 2 - 4)
            media_h = media_w / aspect
            max_media_h = self.device.height * 0.62
            if media_h > max_media_h:
                media_h = max_media_w
                media_w = media_h * aspect

        text_px = self.p(getattr(post, "text_size", 0) or self.TEXT_SIZE)
        meta_px = text_px * 0.75
        chip_emoji_px = text_px * 0.8125
        chip_count_px = chip_emoji_px
        line_gap_px = self.p(getattr(post, "line_spacing", 0) if getattr(post, "line_spacing", 0) else self.TEXT_LINE_SPACING)

        text_w_available = max_inner
        lines: List[text_mod.Line] = []
        line_ascent = line_step = 0.0
        text_h = 0.0
        if post.text:
            lines, text_h, line_ascent, line_step = text_mod.layout(
                post.text, self.fonts, style, 400, text_px,
                self.p(text_w_available), line_gap_px,
            )

        # --- метрики нижней строки (время + просмотры) ---
        meta_f = self.fonts.get(400, meta_px)
        time_w = self.fonts.text_width(post.time, 400, meta_px)
        views_text = post.views_text or (format_views(post.views, post.views_format) if post.show_views else "")
        eye_w = meta_px * 1.17 if views_text else 0
        views_w = self.fonts.text_width(views_text, 400, meta_px) if views_text else 0
        tv_w = time_w + (self.p(6) + eye_w + self.p(3) + views_w if views_text else 0)
        meta_row = max(self.p(16), meta_px * 1.45)   # отдельная строка под время/просмотры

        # --- реакции ---
        chips = [r for r in post.reactions if r.emoji]

        # --- ширина пузыря ---
        text_block_w = max((self.p(0), *[self._line_width(l, style, text_px) for l in lines])) if lines else 0.0
        last_line_w = self._line_width(lines[-1], style, text_px) if lines else 0.0
        content_w = max(text_block_w, self.p(media_w) if media_img else 0.0)

        # реакции тоже задают ширину пузыря: иначе чипы вылезают за его края
        chips_w = 0.0
        if chips:
            chips_w = sum(self._chip_width(r, style, chip_emoji_px, chip_count_px) for r in chips) \
                + self.p(self.REACTION_GAP) * (len(chips) - 1)
            inline_with_chips = chips_w + self.p(10) + tv_w <= self.p(max_inner)
            content_w = max(content_w,
                            chips_w + (self.p(10) + tv_w if inline_with_chips else 0.0))

        # как в Telegram: время может встать в конец последней строки
        want_inline = bool(lines) and not chips and (last_line_w + self.p(10) + tv_w <= self.p(max_inner))
        if want_inline:
            content_w = max(content_w, last_line_w + self.p(10) + tv_w)
        bubble_w = max(content_w + self.p(inner_pad * 2), self.p(90))
        bubble_w = min(bubble_w, self.p(max(max_media_w, max_text_w)))
        inner_w = bubble_w - self.p(inner_pad * 2)
        inline_meta = want_inline and (last_line_w + self.p(10) + tv_w <= inner_w)

        # --- перенос реакций по строкам ---
        chip_rows: List[List[Tuple[Reaction, float]]] = []
        if chips:
            chip_rows = self._layout_chips(chips, inner_w, inner_w - tv_w - self.p(10), style,
                                           chip_emoji_px, chip_count_px)

        # --- высота пузыря ---
        h = self.p(self.BUBBLE_PAD_TOP)
        if media_img is not None:
            h += self.p(media_h)
            if lines:
                h += self.p(2)
        if lines:
            h += text_h
        if chips:
            if lines or media_img is not None:
                h += self.p(5)
            h += len(chip_rows) * self.p(self.REACTION_H) + (len(chip_rows) - 1) * self.p(self.REACTION_GAP)
            last_row_w = sum(cw for _, cw in chip_rows[-1]) + self.p(self.REACTION_GAP) * (len(chip_rows[-1]) - 1)
            if last_row_w + self.p(10) + tv_w > inner_w:
                h += meta_row
        elif not inline_meta:
            h += meta_row
        h += self.p(self.BUBBLE_PAD_BOTTOM)

        last_row_w = 0.0
        if chips:
            last_row_w = sum(cw for _, cw in chip_rows[-1]) + self.p(self.REACTION_GAP) * (len(chip_rows[-1]) - 1)
        if os.environ.get("TG_MOCK_DEBUG"):
            print(f"[debug] bubble_w={bubble_w/self.k:.1f} inner_w={inner_w/self.k:.1f} "
                  f"text_h={text_h/self.k:.1f} rows={len(chip_rows)} h={h/self.k:.1f} "
                  f"tv_w={tv_w/self.k:.1f} last_row_w={last_row_w/self.k:.1f}")

        # --- рисуем пузырь ---
        bubble_x = self.p(bubble_left)
        bubble_y = top
        self.boxes.append(("bubble", (bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + h)))
        tail_w = self.p(8) if post.show_tail else 0.0
        self._draw_bubble(layer, int(round(bubble_x - tail_w)), int(round(bubble_y)),
                          int(round(bubble_w + tail_w)), int(round(h)), int(round(tail_w)))

        cx = bubble_x
        cy = bubble_y + self.p(self.BUBBLE_PAD_TOP)

        # медиа
        if media_img is not None:
            mw, mh = int(round(self.p(media_w))), int(round(self.p(media_h)))
            fitted = self._cover(media_img, mw, mh)
            top_only = bool(lines)
            mimg = self._round_corners(fitted, self.p(self.BUBBLE_RADIUS), top_only=top_only)
            layer.alpha_composite(mimg, (int(round(cx)), int(round(cy))))
            cy += mh + (self.p(2) if lines else 0)

        # текст
        if lines:
            baseline_top = cy
            ascent, descent = self.fonts.ascent_descent(400, text_px)
            for i, line in enumerate(lines):
                baseline = baseline_top + line_ascent + i * line_step
                lw = self._line_width(line, style, text_px)
                self.boxes.append((f"text{i}", (cx + self.p(inner_pad), baseline - ascent,
                                                cx + self.p(inner_pad) + lw, baseline + descent)))
                text_mod.draw_line(layer, line, cx + self.p(inner_pad), baseline,
                                   self.fonts, style, 400, text_px)
            cy = baseline_top + text_h

        # реакции
        meta_y = None
        if chips:
            cy += self.p(5) if (lines or media_img is not None) else 0
            ry = cy
            for ri, row in enumerate(chip_rows):
                rx = cx + self.p(inner_pad)
                for reaction, cw in row:
                    self.boxes.append(("chip", (rx, ry, rx + cw, ry + self.p(self.REACTION_H))))
                    self._chip(layer, rx, ry, cw, reaction, style, chip_emoji_px, chip_count_px)
                    rx += cw + self.p(self.REACTION_GAP)
                ry += self.p(self.REACTION_H + self.REACTION_GAP)
            last_row_w = sum(cw for _, cw in chip_rows[-1]) + self.p(self.REACTION_GAP) * (len(chip_rows[-1]) - 1)
            last_row_y = cy + (len(chip_rows) - 1) * self.p(self.REACTION_H + self.REACTION_GAP)
            if last_row_w + self.p(10) + tv_w <= inner_w:
                meta_y = last_row_y + self.p(self.REACTION_H / 2)
            else:
                meta_y = ry + meta_row / 2
        else:
            if inline_meta:
                meta_y = cy - text_h + (len(lines) - 1) * line_step + line_ascent
            else:
                meta_y = cy + meta_row / 2

        # время + просмотры
        d = ImageDraw.Draw(layer)
        right_edge = cx + bubble_w - self.p(inner_pad)
        tx = right_edge - tv_w
        _ma, _md = self.fonts.ascent_descent(400, meta_px)
        self.boxes.append(("meta", (tx, meta_y - _ma, right_edge, meta_y + _md)))
        d.text((tx, meta_y), post.time, font=meta_f, fill=th.bubble_secondary, anchor="lm")
        if views_text:
            vx = tx + time_w + self.p(6)
            self._eye(layer, vx, meta_y, eye_w, th.bubble_secondary)
            d.text((vx + eye_w + self.p(3), meta_y), views_text, font=meta_f, fill=th.bubble_secondary, anchor="lm")

        return bubble_y + h, bubble_w

    def _line_width(self, line: text_mod.Line, style: text_mod.TextStyle,
                    text_px: Optional[float] = None) -> float:
        return text_mod.line_width(line, self.fonts, style, 400, text_px or self.p(self.TEXT_SIZE))

    def _layout_chips(self, chips: Sequence[Reaction], inner_w: float, last_row_w: float,
                      style: text_mod.TextStyle, emoji_px: Optional[float] = None,
                      count_px: Optional[float] = None):
        rows: List[List[Tuple[Reaction, float]]] = []
        cur: List[Tuple[Reaction, float]] = []
        cur_w = 0.0
        for r in chips:
            w = self._chip_width(r, style, emoji_px, count_px)
            limit = inner_w if not cur else inner_w
            if cur and cur_w + self.p(self.REACTION_GAP) + w > limit:
                rows.append(cur)
                cur, cur_w = [], 0.0
            cur.append((r, w))
            cur_w += w + (self.p(self.REACTION_GAP) if cur[:-1] else 0)
        if cur:
            rows.append(cur)
        return rows

    def _chip_width(self, r: Reaction, style: text_mod.TextStyle,
                    emoji_px: Optional[float] = None, count_px: Optional[float] = None) -> float:
        emoji_px = emoji_px or self.p(self.REACTION_EMOJI)
        count_px = count_px or self.p(13)
        run = self.fonts.emoji.get(r.emoji, emoji_px)
        ew = run.width if run else self.fonts.text_width(r.emoji, 400, emoji_px)
        count = self._reaction_count(r)
        cw = self.fonts.text_width(count, 500, count_px) + self.p(4) if count else 0.0
        return self.p(12) + ew + cw + self.p(2)

    @staticmethod
    def _reaction_count(r: Reaction) -> str:
        if r.count_text:
            return r.count_text
        if r.count:
            return format_views(r.count, "km")
        return ""

    def _chip(self, layer: Image.Image, x: float, y: float, w: float, r: Reaction, style: text_mod.TextStyle,
              emoji_px: Optional[float] = None, count_px: Optional[float] = None) -> None:
        th = self.theme
        overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        h = self.p(self.REACTION_H)
        radius = h / 2
        if r.selected:
            od.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=th.reaction_bg_selected)
            od.rounded_rectangle([x, y, x + w, y + h], radius=radius, outline=th.reaction_border_selected,
                                 width=max(1, int(round(self.p(1.4)))))
        else:
            od.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=th.reaction_bg)
        layer.alpha_composite(overlay)

        emoji_px = emoji_px or self.p(self.REACTION_EMOJI)
        count_px = count_px or self.p(13)
        cx_text = x + self.p(6)
        run = self.fonts.emoji.get(r.emoji, emoji_px)
        if run is not None:
            layer.alpha_composite(run.image, (int(round(cx_text)), int(round(y + h / 2 - run.baseline_y))))
            cx_text += run.width + self.p(4)
        else:
            d = ImageDraw.Draw(layer)
            d.text((cx_text, y + h / 2), r.emoji, font=self.fonts.get(400, emoji_px),
                   fill=th.bubble_text, anchor="lm")
            cx_text += self.fonts.text_width(r.emoji, 400, emoji_px) + self.p(4)
        count = self._reaction_count(r)
        if count:
            d = ImageDraw.Draw(layer)
            color = th.reaction_text_selected if r.selected else th.reaction_text
            d.text((cx_text, y + h / 2), count, font=self.fonts.get(500, count_px), fill=color, anchor="lm")

    def _buttons(self, layer: Image.Image, top: float, bubble_w: float) -> float:
        th = self.theme
        post = self.cfg.post
        rows = self._normalize_buttons(post.buttons)
        x = self.p(self.BUBBLE_LEFT)
        y = top
        for row in rows:
            n = len(row)
            gap = self.p(8)
            w = (bubble_w - gap * (n - 1)) / n
            for i, label in enumerate(row):
                bx = x + i * (w + gap)
                overlay = Image.new("RGBA", layer.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                od.rounded_rectangle([bx, y, bx + w, y + self.p(self.BUTTON_H)],
                                     radius=self.p(10), fill=th.button_bg)
                layer.alpha_composite(overlay)
                d = ImageDraw.Draw(layer)
                d.text((bx + w / 2, y + self.p(self.BUTTON_H) / 2), label,
                       font=self.fonts.get(400, self.p(16)), fill=th.button_text, anchor="mm")
            y += self.p(self.BUTTON_H) + gap
        return y

    @staticmethod
    def _normalize_buttons(buttons) -> List[List[str]]:
        rows: List[List[str]] = []
        for item in buttons:
            if isinstance(item, (list, tuple)):
                rows.append([str(x) for x in item])
            elif isinstance(item, dict):
                rows.append([str(item.get("text", ""))])
            elif isinstance(item, str):
                rows.append([item])
        return rows

    # ============================== геометрия пузыря ==============================
    def _draw_bubble(self, layer: Image.Image, x: int, y: int, w: int, h: int, tail_w: int) -> None:
        r = self.p(self.BUBBLE_RADIUS)
        ss = SS
        mask = Image.new("L", (w * ss, h * ss), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([tail_w * ss, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=255)
        if tail_w:
            # «хвостик» входящего сообщения: две кривые Безье, снизу слева
            bw = w - tail_w
            bh = h
            p0 = (tail_w, (bh - r - 4) * 1.0)
            outer = _bezier(p0, (tail_w, bh - 1.5), (tail_w - self.p(5.0), bh - 0.5), (tail_w - self.p(6.5), bh))
            inner = _bezier((tail_w - self.p(6.5), bh), (tail_w - self.p(3.6), bh + self.p(1.4)),
                            (tail_w + self.p(4), bh + self.p(1.0)), (tail_w + self.p(17), bh))
            poly = [(px * ss, py * ss) for px, py in outer + inner]
            md.polygon(poly, fill=255)
        mask = mask.resize((w, h), Image.LANCZOS)
        bubble = Image.new("RGBA", (w, h), self.theme.bubble)
        bubble.putalpha(mask)
        layer.alpha_composite(bubble, (x, y))
        border = self.theme.bubble_border
        if len(border) > 3 and border[3] > 0:
            ring = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(3)), mask)
            edge = Image.new("RGBA", (w, h), border)
            edge.putalpha(ring)
            layer.alpha_composite(edge, (x, y))

    def _round_corners(self, img: Image.Image, radius: float, top_only: bool = False) -> Image.Image:
        ss = 2
        mask = Image.new("L", (img.width * ss, img.height * ss), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, img.width * ss - 1, img.height * ss - 1], radius=radius * ss, fill=255)
        if top_only:
            md.rectangle([0, img.height * ss - radius * ss, img.width * ss, img.height * ss], fill=255)
        mask = mask.resize((img.width, img.height), Image.LANCZOS)
        out = img.copy()
        out.putalpha(mask)
        return out

    @staticmethod
    def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
        src_w, src_h = img.width, img.height
        scale = max(w / src_w, h / src_h)
        nw, nh = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))
        resized = img.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - w) // 2, (nh - h) // 2
        return resized.crop((left, top, left + w, top + h))

    # ============================== нижняя панель ==============================
    def _bottom_bar(self, img: Image.Image) -> None:
        th = self.theme
        dev = self.device
        kind = (self.cfg.bottom.type or "none").lower()
        panel_h = self.p(self.BOTTOM_PANEL_H)
        top = self.H - self.p(dev.bottom_safe) - panel_h
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        panel = (th.panel_bg[0], th.panel_bg[1], th.panel_bg[2], 245)
        od.rectangle([0, top, self.W, self.H], fill=panel)
        od.line([0, top, self.W, top], fill=th.separator, width=max(1, int(self.k / 3)))
        img.alpha_composite(overlay)

        if kind == "join":
            h = self.p(44)
            y = top + (panel_h - h) / 2
            x = self.p(8)
            w = self.W - self.p(16)
            btn = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(btn).rounded_rectangle([x, y, x + w, y + h], radius=self.p(10), fill=th.accent)
            img.alpha_composite(btn)
            d = ImageDraw.Draw(img)
            d.text((self.W / 2, y + h / 2), self.cfg.bottom.text,
                   font=self.fonts.get(600, self.p(17)), fill=th.accent_contrast, anchor="mm")
        elif kind == "input":
            h = self.p(40)
            y = top + (panel_h - h) / 2
            field = Image.new("RGBA", img.size, (0, 0, 0, 0))
            fd = ImageDraw.Draw(field)
            x0 = self.p(46)
            x1 = self.W - self.p(46)
            fd.rounded_rectangle([x0, y, x1, y + h], radius=h / 2, fill=th.bubble)
            img.alpha_composite(field)
            d = ImageDraw.Draw(img)
            d.text((x0 + self.p(14), y + h / 2), self.cfg.bottom.placeholder,
                   font=self.fonts.get(400, self.p(16)), fill=th.bubble_secondary, anchor="lm")
            self._clip(d, self.p(16), y + h / 2, self.p(22), th.icon_secondary)
            self._smiley(d, self.W - self.p(30), y + h / 2, self.p(22), th.icon_secondary)

    # ============================== home indicator ==============================
    def _home_indicator(self, img: Image.Image) -> None:
        if not self.device.bottom_safe:
            return
        w = self.p(139)
        h = self.p(5)
        x = (self.W - w) / 2
        y = self.H - self.p(8) - h
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=self.theme.home_indicator)
        img.alpha_composite(overlay)

    # ============================== иконки ==============================
    @staticmethod
    def _chevron_left(d: ImageDraw.ImageDraw, x: float, cy: float, size: float, color) -> None:
        w = size * 0.55
        thick = max(1, int(round(size * 0.13)))
        d.line([(x + w, cy - size * 0.42), (x, cy), (x + w, cy + size * 0.42)],
               fill=color, width=thick, joint="curve")

    @staticmethod
    def _bell(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color, muted: bool = False) -> None:
        w = max(1, int(round(size * 0.11)))
        body_w = size * 0.62
        top = cy - size * 0.20
        bottom = cy + size * 0.22
        d.arc([cx - body_w / 2, top - body_w * 0.35, cx + body_w / 2, top + body_w],
              start=180, end=360, fill=color, width=w)
        d.line([(cx - body_w / 2, top + body_w * 0.28), (cx - body_w / 2, bottom - size * 0.06)],
               fill=color, width=w)
        d.line([(cx + body_w / 2, top + body_w * 0.28), (cx + body_w / 2, bottom - size * 0.06)],
               fill=color, width=w)
        d.arc([cx - body_w * 0.42, bottom - size * 0.16, cx + body_w * 0.42, bottom + size * 0.16],
              start=180, end=360, fill=color, width=w)
        d.ellipse([cx - size * 0.11, bottom + size * 0.10, cx + size * 0.11, bottom + size * 0.32], fill=color)
        if muted:
            d.line([(cx - size * 0.55, cy - size * 0.55), (cx + size * 0.55, cy + size * 0.55)],
                   fill=color, width=w)

    @staticmethod
    def _search(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
        r = size * 0.33
        w = max(1, int(round(size * 0.12)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        d.line([(cx + r * 0.72, cy + r * 0.72), (cx + r * 1.5, cy + r * 1.5)], fill=color, width=w)

    @staticmethod
    def _dots(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
        r = size * 0.10
        for dx in (-size * 0.32, 0, size * 0.32):
            d.ellipse([cx + dx - r, cy - r, cx + dx + r, cy + r], fill=color)

    @staticmethod
    def _clip(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
        w = max(1, int(round(size * 0.09)))
        d.rounded_rectangle([cx - size * 0.30, cy - size * 0.38, cx + size * 0.30, cy + size * 0.40],
                            radius=size * 0.24, outline=color, width=w)
        d.ellipse([cx - size * 0.14, cy - size * 0.40, cx + size * 0.14, cy - size * 0.12],
                  outline=color, width=w)

    @staticmethod
    def _smiley(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
        r = size * 0.42
        w = max(1, int(round(size * 0.09)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        er = r * 0.13
        d.ellipse([cx - r * 0.42 - er, cy - r * 0.30 - er, cx - r * 0.42 + er, cy - r * 0.30 + er], fill=color)
        d.ellipse([cx + r * 0.42 - er, cy - r * 0.30 - er, cx + r * 0.42 + er, cy - r * 0.30 + er], fill=color)
        d.arc([cx - r * 0.45, cy - r * 0.30, cx + r * 0.45, cy + r * 0.55], start=20, end=160,
              fill=color, width=w)

    def _eye(self, img: Image.Image, x: float, cy: float, size: float, color) -> None:
        """Иконка «глаз» для просмотров."""
        w = max(1, int(round(size * 0.10)))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        rw = size * 0.94
        rh = size * 0.60
        r = rh * 0.22
        d.rounded_rectangle([x, cy - rh / 2, x + rw, cy + rh / 2], radius=r, outline=color, width=w)
        pr = rh * 0.30
        d.ellipse([x + rw / 2 - pr, cy - pr, x + rw / 2 + pr, cy + pr], fill=color)
        img.alpha_composite(overlay)


# ============================== публичная функция ==============================
def render_config(config: Config, base_dir: Optional[str] = None, fonts: Optional[FontBook] = None) -> Image.Image:
    """Рендерит конфиг в RGBA-изображение."""
    return Renderer(config, fonts=fonts, base_dir=base_dir).render()
