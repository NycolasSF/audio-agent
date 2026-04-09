import os
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.api import state
from apps.api.deps import get_current_user
from core import settings

router = APIRouter()


@router.get("/transcriptions")
async def get_transcriptions(current_user: dict = Depends(get_current_user)):
    return state.repo.list_jobs(user_id=current_user["id"])


@router.delete("/transcriptions/{tid}")
async def delete_trans(tid: str, current_user: dict = Depends(get_current_user)):
    job = state.repo.get_job_owned_by(tid, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Transcrição não encontrada")
    state.repo.delete_job(tid)
    return {"ok": True}


class TitleBody(BaseModel):
    title: str


class SpeakerNamesBody(BaseModel):
    names: dict  # {"SPEAKER_00": "João"}


@router.patch("/transcriptions/{tid}/speakers")
async def update_speakers(
    tid: str,
    body: SpeakerNamesBody,
    current_user: dict = Depends(get_current_user),
):
    job = state.repo.get_job_owned_by(tid, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Transcrição não encontrada")
    state.repo.update_speaker_names(tid, body.names)
    return {"ok": True}


@router.patch("/transcriptions/{tid}/title")
async def update_title(tid: str, body: TitleBody, current_user: dict = Depends(get_current_user)):
    job = state.repo.get_job_owned_by(tid, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Transcrição não encontrada")
    state.repo.update_title(tid, body.title)
    return {"ok": True}


@router.get("/transcriptions/{tid}/status")
async def get_transcription_status(tid: str, current_user: dict = Depends(get_current_user)):
    job = state.repo.get_job_owned_by(tid, current_user["id"])

    if job is None:
        return JSONResponse({"status": "processing", "percent": 0})

    s = job["status"]

    if s == "done":
        return {"status": "done", **job}

    if s == "error":
        # Backward-compat: frontend checks "done" + error field
        return {"status": "done", **job}

    # pending or processing
    if state.pool.is_processing(tid):
        return JSONResponse({"status": "processing", "percent": job["percent"]})

    if s == "pending":
        return JSONResponse({"status": "processing", "percent": 0})

    # status == "processing" but worker isn't on it → server restarted mid-job
    return JSONResponse({"status": "stuck", "percent": 0})


@router.post("/transcriptions/{tid}/retranscribe")
async def retranscribe(
    tid: str,
    model: str = Form("base"),
    language: str = Form("pt"),
    current_user: dict = Depends(get_current_user),
):
    job = state.repo.get_job_owned_by(tid, current_user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Transcrição não encontrada")

    file_path = job.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Arquivo de áudio não encontrado. Gravações antigas podem ter sido apagadas.",
        )

    if model not in settings.VALID_MODELS:
        model = settings.WHISPER_MODEL

    # Quota check before re-enqueuing
    quota = current_user["quota_minutes"]
    if quota != -1:
        used = state.user_repo.get_usage_total(current_user["id"])
        if used >= quota:
            raise HTTPException(status_code=429, detail="Cota de minutos esgotada")

    # Reset job and re-enqueue
    from infra.db import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE jobs
            SET status='pending', percent=0, text=NULL, language=NULL,
                segments=NULL, error=NULL, model=?, input_language=?, updated_at=?
            WHERE id=?
            """,
            (model, language, datetime.now().isoformat(), tid),
        )
        conn.commit()
    finally:
        conn.close()

    state.queue.enqueue(tid)
    return {"id": tid, "status": "processing", "model": model, "language": language}
