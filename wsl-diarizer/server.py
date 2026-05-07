"""Microsservico de diarizacao 3D-Speaker (Alibaba/ModelScope).

Roda dentro do WSL2 (Linux) porque o pipeline ModelScope segfaulta
em Python nativo no Windows. O app principal (Windows) consome este
servico via HTTP em http://127.0.0.1:9020.

Endpoints:
    GET  /health                    -> {"ok": true}
    POST /diarize {file, num_speakers}  -> {"segments": [{start,end,speaker}, ...]}
    POST /unload                    -> libera VRAM/RAM (proxima request recarrega)

Caminhos de audio devem estar em formato Linux (/mnt/f/...). A conversao
de C:\\foo\\bar -> /mnt/c/foo/bar e responsabilidade do cliente.
"""
from __future__ import annotations

import gc
import os
import threading
from pathlib import Path

# Configurar ModelScope offline-first ANTES de qualquer import modelscope
CACHE_DIR = os.environ.get(
    "MODELSCOPE_CACHE",
    "/mnt/f/claude-projetos/audio-agent/models/modelscope",
)
MODEL_PATH = os.environ.get(
    "DIARIZER_MODEL_PATH",
    f"{CACHE_DIR}/iic/speech_campplus_speaker-diarization_common",
)
USE_CUDA = os.environ.get("DIARIZER_USE_CUDA", "true").lower() in ("1", "true", "yes")

os.environ["MODELSCOPE_CACHE"] = CACHE_DIR
os.environ.setdefault("DISABLE_NEW_VERSION", "true")
os.environ.setdefault("MODELSCOPE_LOG_LEVEL", "40")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_lock = threading.Lock()
_pipe = None


def _build_pipeline():
    from modelscope.pipelines import pipeline
    from modelscope.utils.constant import Tasks

    device = "cuda" if USE_CUDA else "cpu"
    return pipeline(
        task=Tasks.speaker_diarization,
        model=MODEL_PATH,
        device=device,
    )


def get_pipe():
    global _pipe
    if _pipe is None:
        with _lock:
            if _pipe is None:
                _pipe = _build_pipeline()
    return _pipe


def drop_pipe() -> bool:
    """Libera o pipeline. Retorna True se havia algo carregado."""
    global _pipe
    with _lock:
        had = _pipe is not None
        _pipe = None
    if had:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
    return had


app = FastAPI(title="audio-agent diarizer (WSL)")


class DiarizeReq(BaseModel):
    file: str
    num_speakers: int | None = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": MODEL_PATH,
        "model_exists": Path(MODEL_PATH).exists(),
        "cuda": USE_CUDA,
        "loaded": _pipe is not None,
    }


@app.post("/diarize")
def diarize(req: DiarizeReq):
    if not Path(req.file).exists():
        raise HTTPException(404, f"audio file not found: {req.file}")

    try:
        kwargs = {"oracle_num_speakers": req.num_speakers} if req.num_speakers else {}
        raw = get_pipe()(req.file, **kwargs)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e

    items = raw.get("text") if isinstance(raw, dict) else raw

    out = []
    for it in items or []:
        if isinstance(it, (list, tuple)):
            start, end, spk = float(it[0]), float(it[1]), int(it[2])
        else:
            start = float(it.get("start", 0))
            end = float(it.get("end") or it.get("stop") or 0)
            spk = int(it.get("spk", it.get("speaker", 0)))
        out.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "speaker": f"SPEAKER_{spk:02d}",
        })
    return {"segments": out}


@app.post("/unload")
def unload():
    return {"unloaded": drop_pipe()}
