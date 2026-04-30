# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python main.py
# Access at http://localhost:8020
```

## First-time migration (from v1 JSON)

If you have an existing `transcriptions/data.json`, migrate it to SQLite before starting:

```bash
python scripts/migrate_json_to_sqlite.py
```

## Installing dependencies

```bash
pip install -r requirements.txt
```

> For NVIDIA GPU support, install PyTorch with CUDA from [pytorch.org](https://pytorch.org/get-started/locally/) **before** running pip install.

## Environment

Copy `.env.example` to `.env` to set the default Whisper model:

```env
WHISPER_MODEL=base   # tiny | base | small | medium | large | large-v3
```

The model can also be changed at runtime via the UI without restarting the server.

## Architecture

**Windows-only** — audio capture depends on WASAPI loopback (`pyaudiowpatch`), which only works on Windows.

### Folder structure

```
audio-agent/
├── apps/
│   ├── api/
│   │   ├── main.py              # FastAPI app assembly
│   │   ├── state.py             # Shared singletons (repo, queue, worker, recorder)
│   │   ├── routes/
│   │   │   ├── transcriptions.py  # GET/DELETE/PATCH/status/retranscribe
│   │   │   └── upload.py          # POST /upload + POST /import-url
│   │   └── ws/
│   │       └── handler.py         # WebSocket /ws handler
│   └── worker/
│       └── worker.py              # Background transcription worker thread
├── core/
│   ├── domain/models.py           # Job dataclass
│   ├── interfaces/                # repo.py + queue.py ABCs
│   ├── services/
│   │   ├── recorder.py            # WASAPI audio capture
│   │   ├── transcriber.py         # Whisper wrapper with progress
│   │   ├── audio_utils.py         # get_audio_duration()
│   │   └── downloader.py          # yt-dlp + httpx download helpers
│   └── settings.py                # Config from env vars
├── infra/
│   ├── db.py                      # SQLite init + schema
│   ├── repo_sqlite.py             # TranscriptionRepo implementation
│   ├── queue_sqlite.py            # JobQueue implementation
│   ├── storage_local.py           # File path helpers
│   └── benchmark.py               # RTF context manager
├── scripts/
│   └── migrate_json_to_sqlite.py  # One-time JSON → SQLite migration
└── static/index.html              # Single-file frontend (no framework)
```

### Data flow

1. **`core/services/recorder.py`** — `AudioRecorder` finds the system's default loopback WASAPI device and records in a background thread, saving to `recordings/recording_<timestamp>.wav`.
2. **`core/services/transcriber.py`** — `transcribe_with_progress()` loads a Whisper model (cached in `_model_cache` by `(model_name, device)`), monkey-patches `whisper.transcribe.tqdm` to intercept progress, and calls `progress_cb(pct)` during transcription.
3. **`apps/worker/worker.py`** — `Worker` is a daemon thread that polls `infra/queue_sqlite.py` for pending jobs. For each job: marks processing → transcribes → marks done/error. Calls `progress_callbacks[job_id](pct)` from the worker thread (thread-safe via `asyncio.run_coroutine_threadsafe`).
4. **`apps/api/`** — FastAPI server:
   - **`/ws` WebSocket** — recording control + real-time progress. On stop: creates job in SQLite, enqueues it, then polls `repo.get_job()` every 0.5s and forwards progress/completion to the client. 25s timeout heartbeat (ping/pong) detects unexpected recording drops.
   - **REST endpoints** — `GET /transcriptions`, `DELETE /transcriptions/{tid}`, `PATCH /transcriptions/{tid}/title`, `GET /transcriptions/{tid}/status`, `POST /transcriptions/{tid}/retranscribe`, `POST /upload`, `POST /import-url`.
5. **`static/index.html`** — single-file frontend, no external dependencies. Communicates exclusively through WebSocket + REST. Uses `Date.now()` for recording timer, Web Audio API for sounds, Notifications API for OS alerts.

### Persistence

- `recordings/` — temporary WAV/MP3 files (git-ignored)
- `transcriptions/data.db` — SQLite database (git-ignored). Tables: `jobs`, `job_queue`, `benchmarks`, `speaker_profiles`, `speaker_embeddings`.

### Job lifecycle

```
pending → (worker picks up) → processing → done
                                         ↘ error
```

Status endpoint (`GET /transcriptions/{tid}/status`) returns:
- `"processing"` — job in queue or being processed
- `"done"` — completed or errored (check `error` field)
- `"stuck"` — server restarted while job was in progress

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

`POST /upload` accepts mp3/mp4/wav/m4a/ogg/webm/flac, saves to `recordings/upload_<id>.<ext>`, creates a job in SQLite, enqueues it to the worker, and returns `{id, status: "processing"}`. The client polls `GET /transcriptions/{tid}/status`.

### URL import flow

`POST /import-url` accepts YouTube, Google Drive, or direct audio/video URLs. Creates a pending job immediately (so the client can show a card), then downloads the file in a background thread (yt-dlp or httpx), updates `file_path` + `duration` in SQLite, and enqueues the job for the worker.

### Benchmarking

After every transcription, `infra/benchmark.py` records `(job_id, model, device, audio_duration, transcription_time, rtf)` in the `benchmarks` table. RTF = transcription_time / audio_duration.
