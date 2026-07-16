# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Como USAR a tool (do mundo, em scripts):** este CLAUDE.md cobre só configuração e ajuste do servidor. Para o guia de uso (cliente, exemplos, modelos), veja `tool_transcritor.md` nesta mesma pasta.

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

**Daily usage** — the app spawns the microservice automatically on startup (`apps/api/diarizer_service.py`, hooked into the FastAPI lifespan). Just run:

```powershell
python main.py
```

The startup logs will show `[Diarizer] Microsservico online em http://127.0.0.1:9020.` once `/health` answers. On shutdown the app sends `pkill -f 'uvicorn server:app'` inside WSL and terminates the `wsl.exe` subprocess.

To opt out (run the microservice manually in another terminal), set `DIARIZER_AUTOSTART=false` in `.env`. To run it manually:

```powershell
wsl -d Ubuntu -u root -- /mnt/f/claude-projetos/_infra/transcritor/wsl-diarizer/start.sh
```

If diarization is disabled for every job (`diarize=False`), the microservice doesn't actually need to be running — autostart is best-effort and never blocks the app boot.

**Models** are pre-downloaded under `models/modelscope/` (~110 MB). The microservice uses `/mnt/f/claude-projetos/_infra/transcritor/models/modelscope/` directly — do not delete this folder.

## Transcription engine (faster-whisper)

Transcription runs on **faster-whisper** (CTranslate2), not the reference `openai-whisper`. Same Whisper models, same text quality and word-level timestamps, but ~4-6x faster on GPU — measured **RTF ~0.11 for `medium` on an RTX 3060 Ti** (vs ~0.6 on openai-whisper alone, and >1.0 when two openai-whisper jobs split the card).

`core/services/transcriber.py` keeps the same `transcribe_with_progress()` signature, so the worker is unchanged. It loads a `WhisperModel` (cached by `(model_name, device, compute_type)`) and drives progress by iterating the lazy `segments` generator — no more `tqdm` monkey-patching. All anti-hallucination params are preserved (`condition_on_previous_text=False`, capped temperature, `no_speech`/`logprob`/`compression_ratio` thresholds).

**Long audio is transcribed in 30-min chunks** (decoded once via `decode_audio`, sliced as ndarray, timestamps re-offset). Reason: faster-whisper's `FeatureExtractor` computes the STFT of the whole audio at once and `np.fft.rfft` upcasts to float64/complex128 internally — a 3h file allocates ~6.7 GB of RAM and dies with `Unable to allocate X GiB`. Chunking caps the peak at ~1 GB regardless of duration. Language is detected on the first chunk and pinned for the rest; a word exactly on a chunk boundary may get clipped (cut on silence via VAD if that ever matters).

The CTranslate2 weights are auto-downloaded from HuggingFace on first use (e.g. `medium` ~1.5 GB), cached under `~/.cache/huggingface` — independent of the `openai-whisper` cache.

## Environment

Copy `.env.example` to `.env`:

```env
WHISPER_MODEL=base       # tiny | base | small | medium | large | large-v3
WHISPER_COMPUTE_TYPE=    # blank = float16 on GPU / int8 on CPU. int8_float16 = faster + less VRAM, ~no quality loss
WHISPER_VAD_FILTER=false # true = Silero VAD trims silence (faster + fewer hallucinations; may clip edge speech)
WHISPER_INITIAL_PROMPT=  # optional decoding hint (domain vocabulary, etc.)

DIARIZER_URL=http://127.0.0.1:9020   # WSL microservice (see above)
DIARIZER_TIMEOUT=1800    # seconds — bump for very long audios
DIARIZER_AUTOSTART=true  # false = run the WSL microservice manually

# Worker pool
GPU_UTIL_LIMIT=95        # worker sleeps between segments above this GPU util%. Lower it for a responsive desktop.
CPU_UTIL_LIMIT=50        # same idea for CPU overflow workers
CPU_WORKERS=1            # extra CPU-only workers. SET 0 for GPU batch jobs — see note below.
MODEL_IDLE_TIMEOUT_SECONDS=60  # unload models from VRAM after this many idle seconds (0 = keep hot)
```

The Whisper model can be changed at runtime via the UI without restarting the server.

**Batch tuning (transcribing many files on the GPU, e.g. overnight):** set `CPU_WORKERS=0`. With faster-whisper a single GPU job already runs at RTF ~0.11; a parallel CPU worker only fights the GPU for the same files and *inflates* per-job RTF. One job at a time on the GPU is fastest — running two at once is what caused the >1.0 RTF on the old engine.

## Architecture

**Hybrid Windows + WSL2** — audio capture and faster-whisper transcription run on Windows (WASAPI loopback via `pyaudiowpatch` is Windows-only). Speaker diarization runs in WSL2 (3D-Speaker has no working Windows wheel) as a microservice the app calls over HTTP.

### Folder structure

```
transcritor/
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
│   │   ├── transcriber.py         # faster-whisper wrapper with progress
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
2. **`core/services/transcriber.py`** — `transcribe_with_progress()` loads a faster-whisper `WhisperModel` (cached in `_model_cache` by `(model_name, device, compute_type)`) and iterates the lazy `segments` generator, calling `progress_cb(pct)` between segments (progress = `segment.end / audio_duration`). GPU/CPU throttle and user-cancellation are checked per segment.
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
