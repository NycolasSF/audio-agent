import asyncio
import json
import os
import shutil
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import torch
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from recorder import AudioRecorder
from transcriber import get_device, transcribe_with_progress

app = FastAPI()
recorder = AudioRecorder()
executor = ThreadPoolExecutor(max_workers=2)

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
VALID_MODELS = {"tiny", "base", "small", "medium", "large"}
DEVICE = get_device()

# In-memory progress tracker for REST-based transcriptions (no WebSocket)
_active_progress: dict = {}  # card_id -> percent (0-100)

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

    was_recording = False
    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=25.0)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                if was_recording and not recorder.is_recording:
                    was_recording = False
                    await ws.send_json({
                        "type": "recording_stopped",
                        "message": "Gravação interrompida inesperadamente",
                    })
                continue

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
                if result["success"]:
                    was_recording = True
                else:
                    await ws.send_json({"type": "error", "message": result["message"]})

            elif action == "stop":
                was_recording = False
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


@app.get("/transcriptions/{tid}/status")
async def get_transcription_status(tid: str):
    data = _load_all()
    entry = data.get(tid)
    if entry and entry.get("text"):          # Has transcribed text → done
        return {"status": "done", **entry}
    if tid in _active_progress:              # Actively transcribing right now
        return JSONResponse({"status": "processing", "percent": _active_progress[tid]})
    if entry and entry.get("error"):         # Failed transcription saved
        return {"status": "done", **entry}
    if entry:                                # In data.json but empty text + server restarted = stuck
        return JSONResponse({"status": "stuck", "percent": 0})
    return JSONResponse({"status": "processing", "percent": 0})


@app.post("/transcriptions/{tid}/retranscribe")
async def retranscribe(tid: str, model: str = Form("base")):
    data = _load_all()
    if tid not in data:
        return JSONResponse({"error": "Transcrição não encontrada"}, status_code=404)
    entry = data[tid]
    file_path = entry.get("file", "")
    if not file_path or not os.path.exists(file_path):
        return JSONResponse({"error": "Arquivo de áudio não encontrado. Gravações antigas podem ter sido apagadas."}, status_code=404)
    if model not in VALID_MODELS:
        model = WHISPER_MODEL
    # Reset to processing state
    patch_transcription(tid, text="", language="?", segments=[], model=model, error=None)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        executor,
        lambda: _transcribe_background_rest(
            tid, file_path, model,
            entry.get("timestamp", ""), entry.get("duration", 0.0),
            entry.get("source", ""),
        ),
    )
    return {"id": tid, "status": "processing", "model": model}



# ── Allowed upload extensions ──────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".flac"}
RECORDINGS_DIR = Path("recordings")


def _get_wav_duration(file_path: str) -> float:
    """Return duration in seconds for WAV files; 0.0 for others."""
    try:
        if file_path.endswith(".wav"):
            with wave.open(file_path, "rb") as wf:
                return round(wf.getnframes() / wf.getframerate(), 1)
    except Exception:
        pass
    return 0.0


def _transcribe_background_rest(card_id: str, file_path: str, model_name: str, timestamp: str, duration: float, original_name: str):
    """Transcribe a file and persist the result directly (no WebSocket). Reports progress via _active_progress."""
    _active_progress[card_id] = 0
    try:
        def progress_cb(pct: int):
            _active_progress[card_id] = pct

        result = transcribe_with_progress(file_path, model_name, DEVICE, progress_cb)
        if result["success"]:
            persist_transcription({
                "id": card_id,
                "text": result["text"],
                "language": result["language"],
                "segments": result["segments"],
                "timestamp": timestamp,
                "duration": duration,
                "model": model_name,
                "device": DEVICE,
                "title": "",
                "file": file_path,
                "source": original_name,
            })
        else:
            persist_transcription({
                "id": card_id,
                "text": "",
                "language": "?",
                "segments": [],
                "timestamp": timestamp,
                "duration": duration,
                "model": model_name,
                "device": DEVICE,
                "title": "",
                "file": file_path,
                "source": original_name,
                "error": result.get("error", "Erro desconhecido"),
            })
    except Exception as e:
        persist_transcription({
            "id": card_id,
            "text": "",
            "language": "?",
            "segments": [],
            "timestamp": timestamp,
            "duration": duration,
            "model": model_name,
            "device": DEVICE,
            "title": "",
            "file": file_path,
            "source": original_name,
            "error": str(e),
        })
    finally:
        _active_progress.pop(card_id, None)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), model: str = Form("base")):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"error": f"Formato não suportado: {ext}. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}"},
            status_code=400,
        )
    if model not in VALID_MODELS:
        model = WHISPER_MODEL

    RECORDINGS_DIR.mkdir(exist_ok=True)
    card_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_name = f"upload_{card_id}{ext}"
    dest_path = str(RECORDINGS_DIR / safe_name)

    # Save uploaded file
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    duration = _get_wav_duration(dest_path)

    # Launch transcription in background thread (no WebSocket needed)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        executor,
        lambda: _transcribe_background_rest(card_id, dest_path, model, timestamp, duration, file.filename),
    )

    return {
        "id": card_id,
        "status": "processing",
        "filename": file.filename,
        "timestamp": timestamp,
        "duration": duration,
        "model": model,
        "device": DEVICE,
    }


@app.get("/")
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

