import os

from dotenv import load_dotenv

load_dotenv()

WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")

VALID_MODELS: set = {"tiny", "base", "small", "medium", "large", "large-v3"}

DB_PATH: str = "transcriptions/data.db"

RECORDINGS_DIR: str = "recordings"

TRANSCRIPTIONS_DIR: str = "transcriptions"

ALLOWED_EXTENSIONS: set = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".flac"}
