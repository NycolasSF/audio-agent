import re
from pathlib import Path

import httpx

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/",
    re.IGNORECASE,
)
DRIVE_RE = re.compile(r"https?://drive\.google\.com/", re.IGNORECASE)


def is_ytdlp_source(url: str) -> bool:
    return bool(YOUTUBE_RE.search(url) or DRIVE_RE.search(url))


def download_with_ytdlp(url: str, dest_path: str) -> str:
    """Download audio via yt-dlp. Returns actual output file path."""
    import yt_dlp  # lazy import — optional dependency

    # Strip extension from dest_path; yt-dlp appends its own
    dest_stem = str(Path(dest_path).with_suffix(""))

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": dest_stem + ".%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # yt-dlp always outputs .mp3 after post-processing
    actual_path = dest_stem + ".mp3"
    if not Path(actual_path).exists():
        raise FileNotFoundError(f"yt-dlp output not found at {actual_path}")
    return actual_path


def download_direct(url: str, dest_path: str) -> str:
    """Stream-download a direct audio/video URL via httpx."""
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    return dest_path
