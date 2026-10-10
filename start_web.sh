#!/usr/bin/env sh
# Быстрый запуск веб-интерфейса (Linux / macOS)
cd "$(dirname "$0")" || exit 1
pip install -r requirements.txt
exec python3 app.py "$@"
