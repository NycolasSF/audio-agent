import subprocess
import wave


def get_audio_duration(file_path: str) -> float:
    """Return duration in seconds for any audio/video file.
    Uses ffprobe if available; falls back to wave module for pure WAV."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        val = result.stdout.strip()
        if val and val != "N/A":
            return round(float(val), 1)
    except Exception:
        pass

    # WAV fallback
    try:
        if file_path.endswith(".wav"):
            with wave.open(file_path, "rb") as wf:
                return round(wf.getnframes() / wf.getframerate(), 1)
    except Exception:
        pass

    return 0.0
