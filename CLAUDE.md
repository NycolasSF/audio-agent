# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python main.py
# Access at http://localhost:8000
```

## Installing dependencies

```bash
pip install -r requirements.txt
```

> For NVIDIA GPU support, install PyTorch with CUDA from [pytorch.org](https://pytorch.org/get-started/locally/) **before** running pip install.

## Environment

Copy `.env.example` to `.env` to set the default Whisper model:

```env
WHISPER_MODEL=base   # tiny | base | small | medium | large
```

The model can also be changed at runtime via the UI without restarting the server.

## Architecture

**Windows-only** — audio capture depends on WASAPI loopback (`pyaudiowpatch`), which only works on Windows.

### Data flow

1. **`recorder.py`** — `AudioRecorder` finds the system's default loopback WASAPI device and records it in a background thread, saving raw frames to `recordings/recording_<timestamp>.wav`.
2. **`transcriber.py`** — `transcribe_with_progress()` loads a Whisper model (cached in `_model_cache` dict keyed by `(model_name, device)`), monkey-patches `whisper.transcribe.tqdm` to intercept progress updates, and calls `progress_cb(pct)` during transcription.
3. **`main.py`** — FastAPI server with:
   - **`/ws` WebSocket** — primary channel for recording control and real-time transcription progress. Implements a 25s timeout heartbeat (ping/pong) to keep long recordings alive. Detects unexpected recording drops and notifies the client.
   - **REST endpoints** — `GET /transcriptions`, `DELETE /transcriptions/{tid}`, `PATCH /transcriptions/{tid}/title`, `GET /transcriptions/{tid}/status`, `POST /upload`.
   - **Background tasks** — transcription runs in a `ThreadPoolExecutor` via `asyncio.create_task`, letting users start a new recording while the previous one is still being transcribed.
4. **`static/index.html`** — single-file frontend with no external dependencies. Communicates exclusively through WebSocket + REST. Uses `Date.now()` for the recording timer (stays accurate in background tabs), Web Audio API for sounds, and the Notifications API for OS-level alerts.

### Persistence

- `recordings/` — temporary WAV files (git-ignored)
- `transcriptions/data.json` — all transcription cards, keyed by `card_id` (8-char hex UUID). Git-ignored; created automatically on first use.

### WebSocket message protocol

| Direction | `type` | Purpose |
|-----------|--------|---------|
| server → client | `status` | recording state + device info |
| server → client | `ping` | heartbeat keepalive |
| server → client | `transcription_start` | new card created |
| server → client | `transcription_progress` | `percent` 0–100 |
| server → client | `transcription_complete` | text + segments + language |
| server → client | `transcription_error` | error message |
| server → client | `recording_stopped` | unexpected drop detected |
| client → server | `action: start/stop/status/change_model` | control messages |

### File upload flow

`POST /upload` accepts mp3/mp4/wav/m4a/ogg/webm/flac, saves to `recordings/upload_<id>.<ext>`, runs `_transcribe_background_rest()` in the thread executor (no WebSocket), and returns `{id, status: "processing"}`. The client polls `GET /transcriptions/{tid}/status` to detect completion.
