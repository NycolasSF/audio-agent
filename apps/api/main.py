import torch
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from apps.api import state
from apps.api.auth.models import UsageResponse, UserOut
from apps.api.auth.routes import router as auth_router
from apps.api.deps import get_current_user
from apps.api.routes import transcriptions, upload
from apps.api.ws.handler import websocket_endpoint
from infra.db import init_db

app = FastAPI(title="AudioAgent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    state.worker.start()
    device_label = state.DEVICE.upper()
    if state.DEVICE == "cuda":
        try:
            device_label += f" — {torch.cuda.get_device_name(0)}"
        except Exception:
            pass
    print(f"[Init] Device: {device_label}")


app.include_router(auth_router)
app.include_router(transcriptions.router)
app.include_router(upload.router)
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
    return {
        "total_minutes": total,
        "quota_minutes": quota,
        "remaining_minutes": max(0.0, quota - total),
        "history": history,
    }


@app.get("/")
async def root() -> HTMLResponse:
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
