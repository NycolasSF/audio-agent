import asyncio
import os
import uuid
from datetime import datetime

from fastapi import Query, WebSocket, WebSocketDisconnect

from apps.api import state
from apps.api.auth.jwt import decode_token
from core import settings


async def _poll_job(ws: WebSocket, card_id: str, loop: asyncio.AbstractEventLoop) -> None:
    """Register a WS progress callback and poll SQLite until the job finishes."""
    def _cb(pct: int) -> None:
        asyncio.run_coroutine_threadsafe(
            ws.send_json({"type": "transcription_progress", "id": card_id, "percent": pct}),
            loop,
        )

    state.progress_callbacks[card_id] = _cb
    try:
        # Send 0% immediately so the card shows the progress bar right away
        await ws.send_json({"type": "transcription_progress", "id": card_id, "percent": 0})

        while True:
            await asyncio.sleep(0.5)
            job = state.repo.get_job(card_id)
            if job is None:
                break

            if job["status"] == "done":
                await asyncio.sleep(0)  # flush any in-flight callback messages
                await ws.send_json({"type": "transcription_progress", "id": card_id, "percent": 100})
                await ws.send_json({
                    "type": "transcription_complete",
                    "id": card_id,
                    "text": job["text"] or "",
                    "language": job["language"] or "?",
                    "segments": job["segments"] or [],
                    "error": job["error"],
                })
                break

            elif job["status"] == "error":
                await ws.send_json({
                    "type": "transcription_error",
                    "id": card_id,
                    "message": job["error"] or "Erro desconhecido",
                })
                break

    except Exception as e:
        try:
            await ws.send_json({"type": "transcription_error", "id": card_id, "message": str(e)})
        except Exception:
            pass
    finally:
        state.progress_callbacks.pop(card_id, None)


async def websocket_endpoint(ws: WebSocket, token: str = Query(...)) -> None:
    await ws.accept()

    # Authenticate via JWT query param
    try:
        payload = decode_token(token)
        user = state.user_repo.get_by_id(payload["sub"])
        if not user or not user["is_active"]:
            raise ValueError("Inactive or unknown user")
    except Exception:
        await ws.send_json({"type": "error", "message": "Autenticação inválida"})
        await ws.close(code=4001)
        return

    current_model: str = settings.WHISPER_MODEL

    await ws.send_json({
        "type": "status",
        "recording": False,
        "message": f"Conectado · {state.DEVICE.upper()} · Modelo: {current_model}",
        "device": state.DEVICE,
    })

    loop = asyncio.get_event_loop()
    was_recording = False

    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=25.0)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                if was_recording and not state.recorder.is_recording:
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None, state.recorder.start
                )
                await ws.send_json({
                    "type": "status",
                    "recording": state.recorder.is_recording,
                    "message": result["message"],
                })
                if result["success"]:
                    was_recording = True
                else:
                    await ws.send_json({"type": "error", "message": result["message"]})

            elif action == "stop":
                was_recording = False
                diarize_flag = bool(data.get("diarize", False))
                language_flag = data.get("language", "pt") or "pt"
                stop_result = await asyncio.get_event_loop().run_in_executor(
                    None, state.recorder.stop
                )
                await ws.send_json({
                    "type": "status",
                    "recording": False,
                    "message": "Pronto",
                })

                if not stop_result["success"]:
                    await ws.send_json({"type": "error", "message": stop_result["message"]})
                    continue

                # Quota check before enqueuing
                _quota = user["quota_minutes"]
                used = state.user_repo.get_usage_total(user["id"]) if _quota != -1 else 0
                if _quota != -1 and used >= _quota:
                    await ws.send_json({
                        "type": "error",
                        "message": "Cota de minutos esgotada. Gravação descartada.",
                    })
                    try:
                        os.remove(stop_result["file_path"])
                    except Exception:
                        pass
                    continue

                card_id = uuid.uuid4().hex[:8]
                ts = datetime.now().strftime("%H:%M:%S")
                dur = stop_result["duration"]
                file_path = stop_result["file_path"]

                # Persist job and enqueue for the worker
                state.repo.create_job({
                    "id": card_id,
                    "status": "pending",
                    "model": current_model,
                    "device": state.DEVICE,
                    "timestamp": ts,
                    "duration": dur,
                    "file_path": file_path,
                    "title": "",
                    "source": "",
                    "user_id": user["id"],
                    "diarize": int(diarize_flag),
                    "input_language": language_flag,
                    "created_at": datetime.now().isoformat(),
                })
                state.queue.enqueue(card_id)

                await ws.send_json({
                    "type": "transcription_start",
                    "id": card_id,
                    "duration": dur,
                    "timestamp": ts,
                    "model": current_model,
                    "device": state.DEVICE,
                })

                # Poll job in background — user can record again immediately
                asyncio.create_task(_poll_job(ws, card_id, loop))

            elif action == "change_model":
                model = data.get("model", "base")
                if model in settings.VALID_MODELS:
                    current_model = model
                    await ws.send_json({"type": "model_changed", "model": model})
                else:
                    await ws.send_json({"type": "error", "message": f"Modelo inválido: {model}"})

            elif action == "status":
                await ws.send_json({
                    "type": "status",
                    "recording": state.recorder.is_recording,
                    "duration": state.recorder.get_duration(),
                    "message": "Gravando" if state.recorder.is_recording else "Pronto",
                })

    except WebSocketDisconnect:
        if state.recorder.is_recording:
            state.recorder.stop()
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
