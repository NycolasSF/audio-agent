from pathlib import Path

from core import settings


def ensure_recordings_dir() -> Path:
    p = Path(settings.RECORDINGS_DIR)
    p.mkdir(exist_ok=True)
    return p


def get_upload_path(card_id: str, ext: str) -> str:
    """Return destination path for an uploaded file."""
    return str(ensure_recordings_dir() / f"upload_{card_id}{ext}")


def get_import_path(card_id: str) -> str:
    """Return destination path for a URL-imported file (pre-yt-dlp extension)."""
    return str(ensure_recordings_dir() / f"import_{card_id}.mp3")
