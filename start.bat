@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Servidor ja de pe na porta 8020? Entao anexa o painel (modo leitura), sem subir outro.
netstat -ano | findstr "LISTENING" | findstr ":8020" >nul 2>&1
if %errorlevel%==0 (
  echo.
  echo  AudioAgent ja esta rodando. Abrindo o painel ^(modo leitura, Ctrl+C sai^)...
  echo.
  python -m monitor.viewer
  pause
  exit /b 0
)

echo.
echo  AudioAgent iniciando...
echo  Acesse: http://localhost:8020
echo.
python main.py
pause
