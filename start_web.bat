@echo off
rem Быстрый запуск веб-интерфейса (Windows)
cd /d "%~dp0"
pip install -r requirements.txt
python app.py %*
