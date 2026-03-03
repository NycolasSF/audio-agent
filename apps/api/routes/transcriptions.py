import os
from datetime import datetime

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.api import state
from core import settings

router = APIRouter()


@router.get("/transcriptions")
async def get_transcriptions():
    return state.repo.list_jobs()


@router.delete("/transcriptions/{tid}")
async def delete_trans(tid: str):
    state.repo.delete_job(tid)
    return {"ok": True}


class TitleBody(BaseModel):
    title: str


@router.patch("/transcriptions/{tid}/title")
async def update_title(tid: str, body: TitleBody):
    state.repo.update_title(tid, body.title)
    return {"ok": True}


@router.get("/transcriptions/{tid}/status")
async def get_transcription_status(tid: str):
    job = state.repo.get_job(tid)

    if job is None:
        return JSONResponse({"status": "processing", "percent": 0})

    s = job["status"]

    if s == "done":
        return {"status": "done", **job}

    if s == "error":
        # Maintain backward-compat: frontend checks for "done" + error field
        return {"status": "done", **job}

    # pending or processing
    if state.worker.current_job_id == tid:
        return JSONResponse({"status": "processing", "percent": job["percent"]})

    # In queue or worker picked it but hasn't set current_job_id yet → processing
    if s == "pending":
        return JSONResponse({"status": "processing", "percent": 0})

    # status == "processing" but worker isn't on it → server restarted mid-job
    return JSONResponse({"status": "stuck", "percent": 0})


@router.post("/transcriptions/{tid}/retranscribe")
async def retranscribe(tid: str, model: str = Form("base")):
    job = state.repo.get_job(tid)
    if job is None:
        return JSONResponse({"error": "Transcrição não encontrada"}, status_code=404)

    file_path = job.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return JSONResponse(
            {"error": "Arquivo de áudio não encontrado. Gravações antigas podem ter sido apagadas."},
            status_code=404,
        )

    if model not in settings.VALID_MODELS:
        model = settings.WHISPER_MODEL

    # Reset job fields and re-enqueue
    from infra.db import get_connection
    import json
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE jobs
            SET status='pending', percent=0, text=NULL, language=NULL,
                segments=NULL, error=NULL, model=?, updated_at=?
            WHERE id=?
            """,
            (model, datetime.now().isoformat(), tid),
        )
        conn.commit()
    finally:
        conn.close()

    state.queue.enqueue(tid)
    return {"id": tid, "status": "processing", "model": model}
