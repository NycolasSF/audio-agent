import shutil
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from apps.api import state
from apps.api.deps import get_current_user
from core import settings
from core.services.audio_utils import get_audio_duration
from core.services.downloader import download_direct, download_with_ytdlp, is_ytdlp_source
from infra.storage_local import ensure_recordings_dir, get_import_path, get_upload_path

router = APIRouter()


def _quota_check(current_user: dict):
    quota = current_user["quota_minutes"]
    if quota == -1:
        return None  # unlimited
    used = state.user_repo.get_usage_total(current_user["id"])
    if used >= quota:
        return JSONResponse({"error": "Cota de minutos esgotada"}, status_code=429)
    return None


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    model: str = Form("base"),
    diarize: bool = Form(False),
    language: str = Form("pt"),
    current_user: dict = Depends(get_current_user),
):
    err = _quota_check(current_user)
    if err:
        return err

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"error": f"Formato não suportado: {ext}. Use: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}"},
            status_code=400,
        )
    if model not in settings.VALID_MODELS:
        model = settings.WHISPER_MODEL

    card_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%H:%M:%S")
    dest_path = get_upload_path(card_id, ext)

    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    duration = get_audio_duration(dest_path)

    state.repo.create_job({
        "id": card_id,
        "status": "pending",
        "model": model,
        "device": state.DEVICE,
        "timestamp": timestamp,
        "duration": duration,
        "file_path": dest_path,
        "title": "",
        "source": file.filename,
        "user_id": current_user["id"],
        "diarize": int(diarize),
        "input_language": language,
        "created_at": datetime.now().isoformat(),
    })
    state.queue.enqueue(card_id)

    return {
        "id": card_id,
        "status": "processing",
        "filename": file.filename,
        "timestamp": timestamp,
        "duration": duration,
        "model": model,
        "device": state.DEVICE,
    }


@router.post("/import-url")
async def import_url_endpoint(
    url: str = Form(...),
    model: str = Form("base"),
    diarize: bool = Form(False),
    language: str = Form("pt"),
    current_user: dict = Depends(get_current_user),
):
    """Import audio from a YouTube, Google Drive, or direct audio/video URL."""
    err = _quota_check(current_user)
    if err:
        return err

    url = url.strip()
    if not url:
        return JSONResponse({"error": "URL não pode ser vazia"}, status_code=400)

    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "URL inválida. Use http:// ou https://."}, status_code=400)

    if not is_ytdlp_source(url):
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext and ext not in settings.ALLOWED_EXTENSIONS:
            return JSONResponse(
                {"error": (
                    f"Formato não suportado: {ext}. "
                    f"Use: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))} "
                    "ou um link de YouTube/Drive."
                )},
                status_code=400,
            )

    if model not in settings.VALID_MODELS:
        model = settings.WHISPER_MODEL

    card_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%H:%M:%S")
    user_id = current_user["id"]

    # Derive display name from URL
    parsed = urlparse(url)
    display_name = parsed.netloc + parsed.path
    if len(display_name) > 60:
        display_name = display_name[:57] + "..."

    # Create placeholder job immediately so the client can show a card
    state.repo.create_job({
        "id": card_id,
        "status": "pending",
        "model": model,
        "device": state.DEVICE,
        "timestamp": timestamp,
        "duration": 0.0,
        "file_path": None,
        "title": "",
        "source": url,
        "user_id": user_id,
        "diarize": int(diarize),
        "input_language": language,
        "created_at": datetime.now().isoformat(),
    })

    # Download in background thread, then enqueue for transcription
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _download_and_enqueue, card_id, url, user_id)

    return {
        "id": card_id,
        "status": "processing",
        "source": url,
        "display_name": display_name,
        "timestamp": timestamp,
        "model": model,
        "device": state.DEVICE,
    }


def _download_and_enqueue(card_id: str, url: str, user_id: str) -> None:
    """Download the URL and enqueue for transcription. Runs in a thread."""
    from infra.db import get_connection
    from datetime import datetime as _dt

    ensure_recordings_dir()
    try:
        if is_ytdlp_source(url):
            placeholder = get_import_path(card_id)
            file_path = download_with_ytdlp(url, placeholder)
        else:
            parsed = urlparse(url)
            ext = Path(parsed.path).suffix.lower()
            if ext not in settings.ALLOWED_EXTENSIONS:
                ext = ".mp3"
            file_path = str(Path(settings.RECORDINGS_DIR) / f"import_{card_id}{ext}")
            download_direct(url, file_path)

        duration = get_audio_duration(file_path)

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET file_path=?, duration=?, updated_at=? WHERE id=?",
                (file_path, duration, _dt.now().isoformat(), card_id),
            )
            conn.commit()
        finally:
            conn.close()

        state.queue.enqueue(card_id)

    except Exception as e:
        state.repo.mark_error(card_id, f"Erro no download: {e}")
