"""
Endpoints locais sem autenticação — acessíveis apenas de 127.0.0.1.
Usados pelo Claude Code e outras ferramentas internas para consultar transcrições.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from apps.api import state

router = APIRouter(prefix="/local", tags=["local"])


def _require_localhost(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Acesso apenas local")


def _job_meta(j: dict) -> dict:
    """Retorna campos de metadados sem o texto completo."""
    return {
        "id":        j.get("id"),
        "title":     j.get("title") or j.get("source") or j.get("id"),
        "source":    j.get("source"),
        "model":     j.get("model"),
        "device":    j.get("device"),
        "duration":  j.get("duration"),
        "language":  j.get("language"),
        "timestamp": j.get("timestamp"),
        "status":    j.get("status"),
    }


@router.get("/transcriptions")
async def list_transcriptions(request: Request, limit: int = Query(100, le=500)):
    """Lista todas as transcrições concluídas (metadados, sem texto)."""
    _require_localhost(request)
    jobs = state.repo.list_jobs(limit=limit)
    return [_job_meta(j) for j in jobs if j.get("status") == "done"]


@router.get("/transcriptions/{tid}")
async def get_transcription(tid: str, request: Request):
    """Retorna uma transcrição completa incluindo texto e segmentos."""
    _require_localhost(request)
    job = state.repo.get_job(tid)
    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="Transcrição não encontrada ou ainda em andamento")
    return job


@router.get("/search")
async def search_transcriptions(
    request: Request,
    q: str = Query(..., min_length=1, description="Termo de busca"),
    limit: int = Query(10, le=50),
):
    """
    Busca por título e conteúdo de texto das transcrições.
    Retorna lista com id, título e trecho do texto onde o termo foi encontrado.
    """
    _require_localhost(request)
    q_lower = q.lower()
    jobs = state.repo.list_jobs(limit=500, full=True)  # busca em conteúdo precisa do text inteiro
    results = []

    for j in jobs:
        if j.get("status") != "done":
            continue

        title = (j.get("title") or j.get("source") or "").lower()
        text  = (j.get("text") or "").lower()

        if q_lower not in title and q_lower not in text:
            continue

        # Extrai trecho ao redor da primeira ocorrência
        snippet = ""
        idx = text.find(q_lower)
        if idx >= 0:
            start = max(0, idx - 80)
            end   = min(len(text), idx + len(q_lower) + 120)
            raw   = j.get("text", "")[start:end].replace("\n", " ").strip()
            snippet = ("…" if start > 0 else "") + raw + ("…" if end < len(text) else "")

        results.append({
            **_job_meta(j),
            "snippet":    snippet,
            "match_title": q_lower in title,
            "match_text":  idx >= 0,
        })

        if len(results) >= limit:
            break

    return {"query": q, "total": len(results), "results": results}
