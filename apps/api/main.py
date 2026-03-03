import torch
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from apps.api import state
from apps.api.routes import transcriptions, upload
from apps.api.ws.handler import websocket_endpoint
from infra.db import init_db

app = FastAPI(title="AudioAgent")


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


app.include_router(transcriptions.router)
app.include_router(upload.router)
app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/")
async def root() -> HTMLResponse:
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
