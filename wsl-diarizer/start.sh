#!/usr/bin/env bash
# Boot do microsservico de diarizacao no WSL2.
# Uso (no Windows PowerShell):
#   wsl -d Ubuntu -u root -- /mnt/f/claude-projetos/audio-agent/wsl-diarizer/start.sh
set -euo pipefail

VENV=/opt/audio-diarizer/venv
APP_DIR=/mnt/f/claude-projetos/audio-agent/wsl-diarizer
HOST=${DIARIZER_HOST:-127.0.0.1}
PORT=${DIARIZER_PORT:-9020}

cd "$APP_DIR"
exec "$VENV/bin/uvicorn" server:app --host "$HOST" --port "$PORT" --log-level info
