import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import torch
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from recorder import AudioRecorder
from transcriber import get_device, transcribe_with_progress

app = FastAPI()
recorder = AudioRecorder()
executor = ThreadPoolExecutor(max_workers=2)

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
VALID_MODELS = {"tiny", "base", "small", "medium", "large"}
DEVICE = get_device()

print(f"[Init] Device: {DEVICE.upper()}"
      + (f" — {torch.cuda.get_device_name(0)}" if DEVICE == "cuda" else ""))

TRANSCRIPTIONS_FILE = Path("transcriptions/data.json")


def _load_all() -> dict:
    TRANSCRIPTIONS_FILE.parent.mkdir(exist_ok=True)
    if TRANSCRIPTIONS_FILE.exists():
        try:
            return json.loads(TRANSCRIPTIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_all(data: dict):
    TRANSCRIPTIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def persist_transcription(entry: dict):
    data = _load_all()
    data[entry["id"]] = entry
    _save_all(data)


def remove_transcription(tid: str):
    data = _load_all()
    data.pop(tid, None)
    _save_all(data)


def patch_transcription(tid: str, **fields):
    data = _load_all()
    if tid in data:
        data[tid].update(fields)
        _save_all(data)


async def run_in_thread(func):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func)


async def _transcribe_background(ws: WebSocket, card_id: str, file_path: str, model_name: str, timestamp: str, duration: float):
    loop = asyncio.get_event_loop()

    def progress_cb(pct: int):
        asyncio.run_coroutine_threadsafe(
            ws.send_json({"type": "transcription_progress", "id": card_id, "percent": pct}),
            loop,
        )

    try:
        # Send 0% immediately so card shows progress bar right away
        await ws.send_json({"type": "transcription_progress", "id": card_id, "percent": 0})

        t = await run_in_thread(
            lambda: transcribe_with_progress(file_path, model_name, DEVICE, progress_cb)
        )

        # Yield to event loop so any run_coroutine_threadsafe progress messages flush first
        await asyncio.sleep(0)
        await ws.send_json({"type": "transcription_progress", "id": card_id, "percent": 100})

        if t["success"]:
            await ws.send_json({
                "type": "transcription_complete",
                "id": card_id,
                "text": t["text"],
                "language": t["language"],
                "segments": t["segments"],
            })
            persist_transcription({
                "id": card_id,
                "text": t["text"],
                "language": t["language"],
                "segments": t["segments"],
                "timestamp": timestamp,
                "duration": duration,
                "model": model_name,
                "device": DEVICE,
                "title": "",
                "file": file_path,
            })
        else:
            await ws.send_json({
                "type": "transcription_error",
                "id": card_id,
                "message": t.get("error", "Erro desconhecido"),
            })
    except Exception as e:
        try:
            await ws.send_json({"type": "transcription_error", "id": card_id, "message": str(e)})
        except Exception:
            pass


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global WHISPER_MODEL
    await ws.accept()
    await ws.send_json({
        "type": "status",
        "recording": False,
        "message": f"Conectado · {DEVICE.upper()} · Modelo: {WHISPER_MODEL}",
        "device": DEVICE,
    })

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") != "action":
                continue

            action = data.get("action")

            if action == "start":
                result = await run_in_thread(recorder.start)
                await ws.send_json({
                    "type": "status",
                    "recording": recorder.is_recording,
                    "message": result["message"],
                })
                if not result["success"]:
                    await ws.send_json({"type": "error", "message": result["message"]})

            elif action == "stop":
                stop_result = await run_in_thread(recorder.stop)
                await ws.send_json({
                    "type": "status",
                    "recording": False,
                    "message": "Pronto",
                })

                if not stop_result["success"]:
                    await ws.send_json({"type": "error", "message": stop_result["message"]})
                    continue

                card_id = uuid.uuid4().hex[:8]
                ts = datetime.now().strftime("%H:%M:%S")
                dur = stop_result["duration"]
                await ws.send_json({
                    "type": "transcription_start",
                    "id": card_id,
                    "duration": dur,
                    "timestamp": ts,
                    "model": WHISPER_MODEL,
                    "device": DEVICE,
                })

                # Launch in background — user can record again immediately
                asyncio.create_task(
                    _transcribe_background(ws, card_id, stop_result["file_path"], WHISPER_MODEL, ts, dur)
                )

            elif action == "change_model":
                model = data.get("model", "base")
                if model in VALID_MODELS:
                    WHISPER_MODEL = model
                    await ws.send_json({"type": "model_changed", "model": model})
                else:
                    await ws.send_json({"type": "error", "message": f"Modelo inválido: {model}"})

            elif action == "status":
                await ws.send_json({
                    "type": "status",
                    "recording": recorder.is_recording,
                    "duration": recorder.get_duration(),
                    "message": "Gravando" if recorder.is_recording else "Pronto",
                })

    except WebSocketDisconnect:
        if recorder.is_recording:
            recorder.stop()
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


@app.get("/transcriptions")
async def get_transcriptions():
    data = _load_all()
    items = sorted(data.values(), key=lambda x: x.get("timestamp", ""))
    return items


@app.delete("/transcriptions/{tid}")
async def delete_trans(tid: str):
    remove_transcription(tid)
    return {"ok": True}


class TitleBody(BaseModel):
    title: str


@app.patch("/transcriptions/{tid}/title")
async def update_title(tid: str, body: TitleBody):
    patch_transcription(tid, title=body.title)
    return {"ok": True}


@app.get("/")
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
