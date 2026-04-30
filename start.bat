@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  AudioAgent iniciando...
echo  Acesse: http://localhost:8020
echo.
python main.py
pause
