"""Auto-start do microsservico de diarizacao no WSL2.

Quando o app FastAPI sobe, este modulo:
  1. Checa se ja existe alguem respondendo em DIARIZER_URL/health
     (talvez o usuario subiu manualmente). Se sim, nao faz nada.
  2. Caso contrario, spawna ``wsl -d <distro> -u <user> -- <start.sh>``
     em subprocess e espera /health responder OK (timeout configuravel).
  3. No shutdown, manda pkill no uvicorn dentro do WSL e termina o
     subprocess do wsl.exe.

Tudo isto e best-effort: se DIARIZER_AUTOSTART=false, ou se o WSL nao
estiver instalado, ou se o /health nao subir a tempo, o app continua
funcionando — apenas jobs com diarize=True falharao mais tarde com
mensagem de conexao recusada.
"""
from __future__ import annotations

import subprocess
import time

import httpx

from core import settings


_proc: subprocess.Popen | None = None


def _health_ok(timeout: float = 1.5) -> bool:
    try:
        r = httpx.get(f"{settings.DIARIZER_URL}/health", timeout=timeout)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False


def start() -> None:
    """Sobe o microsservico no WSL e espera /health.

    Idempotente: se ja houver alguem respondendo em DIARIZER_URL,
    nao spawna nada.
    """
    global _proc

    if not settings.DIARIZER_AUTOSTART:
        print("[Diarizer] DIARIZER_AUTOSTART desligado — microsservico nao sera iniciado.")
        return

    if _health_ok():
        print(f"[Diarizer] Ja respondendo em {settings.DIARIZER_URL} — pulando autostart.")
        return

    cmd = [
        "wsl",
        "-d", settings.DIARIZER_WSL_DISTRO,
        "-u", settings.DIARIZER_WSL_USER,
        "--",
        settings.DIARIZER_START_SCRIPT,
    ]
    print(f"[Diarizer] Subindo microsservico: {' '.join(cmd)}")
    try:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except FileNotFoundError:
        print("[Diarizer] wsl.exe nao encontrado no PATH — microsservico nao sera iniciado.")
        _proc = None
        return
    except Exception as e:
        print(f"[Diarizer] Falha ao spawnar microsservico: {e}")
        _proc = None
        return

    deadline = time.time() + settings.DIARIZER_STARTUP_TIMEOUT
    while time.time() < deadline:
        if _proc.poll() is not None:
            print(f"[Diarizer] Subprocess do WSL morreu antes de subir (exit={_proc.returncode}).")
            _proc = None
            return
        if _health_ok():
            print(f"[Diarizer] Microsservico online em {settings.DIARIZER_URL}.")
            return
        time.sleep(0.5)

    print(f"[Diarizer] Timeout de {settings.DIARIZER_STARTUP_TIMEOUT}s "
          f"esperando /health — seguindo sem garantia de diarizacao.")


def stop() -> None:
    """Mata o uvicorn dentro do WSL e o subprocess do wsl.exe."""
    global _proc

    if _proc is None:
        return

    try:
        subprocess.run(
            [
                "wsl",
                "-d", settings.DIARIZER_WSL_DISTRO,
                "-u", settings.DIARIZER_WSL_USER,
                "--",
                "pkill", "-f", "uvicorn server:app",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except Exception as e:
        print(f"[Diarizer] Aviso: falha no pkill via WSL: {e}")

    try:
        _proc.terminate()
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _proc.kill()
    except Exception:
        pass
    finally:
        _proc = None
        print("[Diarizer] Microsservico encerrado.")
