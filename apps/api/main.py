import torch
from typing import List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from apps.api import diarizer_service, state
from apps.api.auth.models import AdminUserItem, QuotaUpdateBody, UsageResponse, UserOut
from apps.api.auth.routes import router as auth_router
from apps.api.deps import get_admin_user, get_current_user
from apps.api.routes import transcriptions, upload, local
from apps.api.ws.handler import websocket_endpoint
from infra.db import init_db

app = FastAPI(title="Transcritor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8020", "http://127.0.0.1:8020"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    diarizer_service.start()
    state.pool.start()
    device_label = state.DEVICE.upper()
    if state.DEVICE == "cuda":
        try:
            device_label += f" — {torch.cuda.get_device_name(0)}"
        except Exception:
            pass
    print(f"[Init] Device: {device_label}")


@app.on_event("shutdown")
async def shutdown() -> None:
    diarizer_service.stop()


app.include_router(auth_router)
app.include_router(transcriptions.router)
app.include_router(upload.router)
app.include_router(local.router)
app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return {
        **current_user,
        "usage_minutes": state.user_repo.get_usage_total(current_user["id"]),
    }


@app.get("/usage", response_model=UsageResponse)
async def usage(current_user: dict = Depends(get_current_user)):
    total = state.user_repo.get_usage_total(current_user["id"])
    quota = current_user["quota_minutes"]
    history = state.user_repo.get_usage_history(current_user["id"])
    remaining = -1.0 if quota == -1 else max(0.0, quota - total)
    return {
        "total_minutes": total,
        "quota_minutes": quota,
        "remaining_minutes": remaining,
        "history": history,
    }


@app.get("/admin/users", response_model=List[AdminUserItem])
async def admin_list_users(admin: dict = Depends(get_admin_user)):
    return state.user_repo.get_all_users()


@app.patch("/admin/users/{user_id}/quota")
async def admin_update_quota(
    user_id: str,
    body: QuotaUpdateBody,
    admin: dict = Depends(get_admin_user),
):
    ok = state.user_repo.update_quota(user_id, body.quota_minutes)
    if not ok:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"ok": True}


@app.get("/")
async def root() -> HTMLResponse:
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
