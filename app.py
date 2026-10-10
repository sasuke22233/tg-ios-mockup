"""
Веб-редактор шаблона: правите время поста, реакции, время на телефоне —
превью обновляется на лету, результат скачивается PNG или config.json.

Запуск:
    pip install -r requirements.txt
    python app.py                 # http://localhost:5000
    python app.py --port 8080
"""

from __future__ import annotations

import argparse
import io
import json
import os
import secrets
from typing import Dict, Optional

from flask import Flask, Response, jsonify, render_template, request, send_file

from tg_mock.config import Config
from tg_mock.fonts import FontBook
from tg_mock.render import render_config
from tg_mock.theme import DEVICES, THEMES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

FONTS = FontBook()
STORE: Dict[str, Config] = {}
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

EXAMPLES_DIR = os.path.join(BASE_DIR, "examples")
PRESETS: Dict[str, Optional[str]] = {
    "default": None,
    "dark_photo": os.path.join(EXAMPLES_DIR, "dark_photo.json"),
    "light_text": os.path.join(EXAMPLES_DIR, "light_text.json"),
}
PRESETS = {k: (v if v and os.path.exists(v) else None) for k, v in PRESETS.items()}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


# ------------------------------------------------------------------ страницы
@app.get("/")
def index():
    return render_template(
        "index.html",
        devices={k: d.name for k, d in DEVICES.items()},
        themes={k: k for k in THEMES},
        defaults=Config().to_dict(),
        has_emoji=FONTS.emoji.available,
        has_sf=bool(FONTS.sf_path),
    )


# ------------------------------------------------------------------ API
@app.post("/api/render")
def api_render():
    """Принимает JSON-конфиг, сохраняет его и отдаёт ссылку на превью."""
    data = request.get_json(force=True, silent=True) or {}
    cfg = Config.from_dict(data)
    token = data.get("_token") or secrets.token_hex(8)
    STORE[token] = cfg
    return jsonify({"token": token, "preview": f"/preview/{token}.png", "download": f"/download/{token}.png"})


@app.get("/preview/<token>.png")
def preview(token: str):
    cfg = STORE.get(token) or Config()
    img = render_config(cfg, base_dir=BASE_DIR, fonts=FONTS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    resp = Response(buf.getvalue(), mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/download/<token>.png")
def download(token: str):
    cfg = STORE.get(token) or Config()
    img = render_config(cfg, base_dir=BASE_DIR, fonts=FONTS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    name = "telegram_post_" + (cfg.channel.name or "channel").replace(" ", "_") + ".png"
    return send_file(buf, mimetype="image/png", as_attachment=True, download_name=name)


@app.get("/download-config/<token>.json")
def download_config(token: str):
    cfg = STORE.get(token) or Config()
    buf = io.BytesIO()
    import json

    buf.write(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return send_file(buf, mimetype="application/json", as_attachment=True, download_name="config.json")


@app.get("/api/config/<token>")
def api_config(token: str):
    cfg = STORE.get(token) or Config()
    return jsonify(cfg.to_dict())


@app.get("/api/presets")
def api_presets():
    """Список готовых пресетов (examples/*.json + значения по умолчанию)."""
    return jsonify(list(PRESETS))


@app.get("/api/presets/<name>")
def api_preset(name: str):
    if name not in PRESETS:
        return jsonify({"error": "нет такого пресета"}), 404
    path = PRESETS[name]
    if path is None:
        return jsonify(Config().to_dict())
    with open(path, "r", encoding="utf-8") as fh:
        return jsonify(json.load(fh))


@app.post("/api/upload")
def api_upload():
    """Сохраняет картинку (медиа поста или аватар) и возвращает относительный путь."""
    if "file" not in request.files:
        return jsonify({"error": "нет файла"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "пустое имя файла"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"допустимые форматы: {', '.join(sorted(ALLOWED_EXT))}"}), 400
    name = secrets.token_hex(6) + ext
    path = os.path.join(UPLOAD_DIR, name)
    file.save(path)
    return jsonify({"path": os.path.join("uploads", name).replace(os.sep, "/")})


def main() -> None:
    parser = argparse.ArgumentParser(description="Веб-редактор шаблона скриншота Telegram-канала")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"Откройте в браузере: http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
