@echo off
chcp 65001 >nul
echo.
echo  ╔══════════════════════════════════════╗
echo  ║     AudioAgent — Instalação          ║
echo  ╚══════════════════════════════════════╝
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo  ERRO: Python nao encontrado.
  echo  Instale Python 3.10 ou superior em https://python.org
  pause
  exit /b 1
)

echo  Instalando dependencias...
echo.
pip install -r requirements.txt

if errorlevel 1 (
  echo.
  echo  ERRO: falha ao instalar dependencias.
  pause
  exit /b 1
)

echo.
echo  Instalacao concluida!
echo  Execute start.bat para iniciar o servidor.
echo.
pause
