"""Консольная утилита: сборка скриншота из JSON-конфига."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from .config import Config, reactions_from_pairs
from .fonts import FontBook
from .render import render_config
from .theme import DEVICES, THEMES

DEFAULT_CONFIG_NAME = "config.json"


def _coerce(value: str) -> Any:
    low = value.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except Exception:
            pass
    return value


def _set_path(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = getattr(cur, p)
    setattr(cur, parts[-1], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tg_mock",
        description="Генератор шаблона скриншота поста Telegram-канала (iOS).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python -m tg_mock                          # собрать config.json -> output/post.png\n"
            "  python -m tg_mock -c examples/light.json -o out.png\n"
            "  python -m tg_mock --set post.time=21:07 --set post.views=8800\n"
            "  python -m tg_mock --set status.time=23:15 --theme light --scale 2\n"
            "  python -m tg_mock --init                   # создать config.json с настройками по умолчанию\n"
            "  python -m tg_mock --list-devices\n"
        ),
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_NAME, help="путь к JSON-конфигу")
    parser.add_argument("-o", "--output", default=None, help="куда сохранить PNG (по умолчанию из конфига)")
    parser.add_argument("--theme", choices=sorted(THEMES), default=None, help="перекрыть тему")
    parser.add_argument("--device", default=None, help="перекрыть модель устройства")
    parser.add_argument("--scale", type=int, choices=(1, 2, 3), default=None, help="масштаб рендера (1/2/3)")
    parser.add_argument("--set", action="append", default=[], metavar="ПУТЬ=ЗНАЧЕНИЕ",
                        help="изменить любое поле, например --set post.time=21:07")
    parser.add_argument("--init", action="store_true", help="создать/перезаписать config.json значениями по умолчанию")
    parser.add_argument("--list-devices", action="store_true", help="показать доступные устройства")
    parser.add_argument("--quiet", action="store_true", help="не печатать лишнего")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_devices:
        for key, dev in DEVICES.items():
            print(f"{key:20s} {dev.name:20s} {dev.width:g}x{dev.height:g}pt "
                  f"({int(dev.width * dev.scale)}x{int(dev.height * dev.scale)}px)")
        return 0

    if args.init or not os.path.exists(args.config):
        cfg = Config()
        cfg.save(args.config)
        print(f"Создан конфиг: {os.path.abspath(args.config)}")
        if args.init:
            return 0

    cfg = Config.load(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config)) or os.getcwd()

    if args.theme:
        cfg.screen.theme = args.theme
    if args.device:
        cfg.screen.device = args.device
    if args.scale:
        cfg.screen.scale = args.scale

    for item in args.set:
        if "=" not in item:
            print(f"Пропущено (нет '='): {item}", file=sys.stderr)
            continue
        path, value = item.split("=", 1)
        try:
            _set_path(cfg, path.strip(), _coerce(value))
        except Exception as exc:  # noqa: BLE001
            print(f"Не удалось применить {item}: {exc}", file=sys.stderr)

    fonts = FontBook()
    image = render_config(cfg, base_dir=base_dir, fonts=fonts)

    out = args.output or cfg.screen.output
    out_path = out if os.path.isabs(out) else os.path.join(os.getcwd(), out)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    image.save(out_path)

    if not args.quiet:
        print(f"Готово: {os.path.abspath(out_path)}  ({image.width}x{image.height}px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
