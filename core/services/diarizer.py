"""Speaker diarization via WSL2 microservice (3D-Speaker no Linux).

ModelScope/3D-Speaker segfauta no Python nativo do Windows, entao a
diarizacao roda dentro do WSL2 num microsservico FastAPI (porta 9020).
Este modulo e um thin client HTTP que preserva a interface publica
(diarize, merge_speaker_labels, unload_pipeline) consumida pelo worker.

Veja ``wsl-diarizer/server.py`` para o servidor.
"""
from __future__ import annotations

import re

import httpx

from core import settings


_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def _to_wsl_path(path: str) -> str:
    """Converte ``F:\\foo\\bar`` em ``/mnt/f/foo/bar``.

    Caminhos ja em formato POSIX sao retornados como estao.
    """
    s = str(path).replace("\\", "/")
    m = _DRIVE_RE.match(s)
    if m:
        drive, rest = m.group(1).lower(), m.group(2)
        return f"/mnt/{drive}/{rest}"
    return s


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.DIARIZER_URL, timeout=settings.DIARIZER_TIMEOUT)


def diarize(file_path: str, num_speakers: int | None = None) -> list:
    """Run diarization on *file_path* via the WSL microservice.

    Returns ``[{start, end, speaker}, ...]``.
    Raises on any error (caller is responsible for try/except).
    """
    payload = {
        "file": _to_wsl_path(file_path),
        "num_speakers": num_speakers,
    }
    with _client() as c:
        r = c.post("/diarize", json=payload)
        r.raise_for_status()
    return r.json()["segments"]


def unload_pipeline() -> None:
    """Pede ao microsservico que libere o pipeline (VRAM/RAM).

    Chamado pelo pool quando o worker fica ocioso. Nao levanta
    excecao caso o microsservico esteja indisponivel.
    """
    try:
        with _client() as c:
            c.post("/unload")
        print("[Diarizer] Pipeline descarregado da memoria (WSL).")
    except Exception as e:
        print(f"[Diarizer] Aviso: falha ao chamar /unload no microsservico: {e}")


def merge_speaker_labels(whisper_segs: list, diarize_segs: list) -> list:
    """Annotate Whisper segments with diarization speaker label.

    Para cada segmento Whisper escolhe o speaker com maior overlap
    temporal. Cai em ``"UNKNOWN"`` se nao houver overlap.
    """
    out = []
    for seg in whisper_segs:
        best, best_ov = "UNKNOWN", 0.0
        for d in diarize_segs:
            ov = min(seg["end"], d["end"]) - max(seg["start"], d["start"])
            if ov > best_ov:
                best_ov, best = ov, d["speaker"]
        out.append({**seg, "speaker": best})
    return out
