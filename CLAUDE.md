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

## Speaker diarization (WSL2 microservice)

3D-Speaker (Alibaba/ModelScope) segfaults under native Python on Windows, so diarization runs inside **WSL2 Ubuntu** as a separate FastAPI microservice on port 9020. The Windows app talks to it over HTTP.

**One-time WSL setup** (already done on this machine — re-run only on a fresh box):

```powershell
# 1. Install Ubuntu in WSL2
wsl --install -d Ubuntu --no-launch
wsl --set-default Ubuntu

# 2. Inside Ubuntu (as root): install uv + Python 3.12 + venv + PyTorch CUDA + modelscope deps
wsl -d Ubuntu -u root -- bash -c "
  curl -LsSf https://astral.sh/uv/install.sh | sh &&
  apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg libsndfile1 &&
  /root/.local/bin/uv python install 3.12 &&
  /root/.local/bin/uv venv --python 3.12 /opt/audio-diarizer/venv &&
  export VIRTUAL_ENV=/opt/audio-diarizer/venv &&
  /root/.local/bin/uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 &&
  /root/.local/bin/uv pip install 'numpy<2' modelscope datasets funasr fastapi uvicorn soundfile \
    addict simplejson sortedcontainers pillow opencv-python-headless hdbscan umap-learn pyyaml kaldiio librosa scipy
"
```

**Daily usage** — start the diarizer service before launching the Windows app (any terminal):

```powershell
wsl -d Ubuntu -u root -- /mnt/f/claude-projetos/audio-agent/wsl-diarizer/start.sh
```

Then in another terminal:

```powershell
python main.py
```

If diarization is disabled for a job (`diarize=False`), the microservice doesn't need to be running.

**Models** are pre-downloaded under `models/modelscope/` (~110 MB). The microservice uses `/mnt/f/claude-projetos/audio-agent/models/modelscope/` directly — do not delete this folder.

## Environment

Copy `.env.example` to `.env` to set the default Whisper model and diarizer URL:

```env
WHISPER_MODEL=base       # tiny | base | small | medium | large | large-v3
DIARIZER_URL=http://127.0.0.1:9020   # WSL microservice (see above)
DIARIZER_TIMEOUT=1800    # seconds — bump for very long audios
```

The Whisper model can be changed at runtime via the UI without restarting the server.

## Architecture

**Hybrid Windows + WSL2** — audio capture and Whisper transcription run on Windows (WASAPI loopback via `pyaudiowpatch` is Windows-only). Speaker diarization runs in WSL2 (3D-Speaker has no working Windows wheel) as a microservice the app calls over HTTP.

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
│   │   ├── diarizer.py            # HTTP client to WSL microservice
│   │   └── downloader.py          # yt-dlp + httpx download helpers
│   └── settings.py                # Config from env vars
├── infra/
│   ├── db.py                      # SQLite init + schema
│   ├── repo_sqlite.py             # TranscriptionRepo implementation
│   ├── queue_sqlite.py            # JobQueue implementation
│   ├── storage_local.py           # File path helpers
│   └── benchmark.py               # RTF context manager
├── wsl-diarizer/                  # microservice running INSIDE WSL2 Ubuntu
│   ├── server.py                  # FastAPI: /health /diarize /unload (port 9020)
│   ├── start.sh                   # uvicorn boot script
│   └── smoke_test.py              # standalone PoC for the 3D-Speaker pipeline
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
