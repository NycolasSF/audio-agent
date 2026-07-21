# -*- coding: utf-8 -*-
"""Cliente CANÔNICO do transcritor (localhost:8020) — stdlib pura (urllib).

POLÍTICA DO HUB: TODA transcrição de áudio/vídeo no claude-projetos passa por
ESTE cliente -> transcritor. É PROIBIDO carregar Whisper local
(`whisper.load_model`, `faster_whisper.WhisperModel`) em qualquer script: a GPU
é única (8 GB) e dois modelos competindo causam CUDA out of memory. O servidor
serializa os jobs numa fila e é o ÚNICO dono da GPU.

Uso típico (de qualquer pasta do hub):

    import sys
    sys.path.insert(0, r"F:\\claude-projetos\\_infra\\transcritor\\clients")
    from transcritor_client import transcribe_file, transcribe_media

    job = transcribe_file(r"C:\\audio.wav", model="large-v3", language="pt")
    print(job["text"])
    for seg in job["segments"]:
        for w in seg.get("words", []):
            ...  # w["word"], w["start"], w["end"], w["probability"]

Para vídeos .mov (não aceitos pelo /upload) use transcribe_media(), que extrai
um WAV 16 kHz mono via ffmpeg antes de subir.

MODELOS: tiny | base | small | medium | large-v3. Numa GPU de 8 GB o large-v3
roda em float16 desde que seja o único modelo na placa (o servidor garante isso).
Se faltar VRAM, suba o servidor com WHISPER_COMPUTE_TYPE=int8_float16.
"""
import json
import os
import subprocess
import time
import uuid
import urllib.request

API = os.getenv("TRANSCRITOR_URL", "http://localhost:8020")

# Extensões que o /upload aceita direto (espelha core/settings ALLOWED_EXTENSIONS).
_DIRECT_EXTS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm", ".flac"}

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")


def _env_var(key: str) -> str | None:
    """Lê var de ambiente, com fallback pro .env do transcritor (stdlib, sem dotenv)."""
    if key in os.environ:
        return os.environ[key]
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


def login(api: str = API) -> str:
    email = _env_var("TRANSCRITOR_EMAIL")
    password = _env_var("TRANSCRITOR_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "TRANSCRITOR_EMAIL/TRANSCRITOR_PASSWORD não definidas "
            f"(defina no ambiente ou em {_ENV_PATH})"
        )
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        api + "/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def wait_server(timeout: int = 180, api: str = API) -> str:
    """Aguarda o transcritor responder e devolve um token. Levanta se não subir."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            return login(api)
        except Exception:
            time.sleep(4)
    raise RuntimeError(f"transcritor fora do ar em {api} (rode start.bat / python main.py)")


def _upload(token: str, path: str, model: str, language: str, diarize: bool, api: str) -> str:
    boundary = uuid.uuid4().hex
    fname = os.path.basename(path)
    ext = os.path.splitext(fname)[1].lower()
    ctype = "video/mp4" if ext == ".mp4" else "audio/wav" if ext == ".wav" else "application/octet-stream"

    def part(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n").encode()

    body = part("model", model) + part("language", language) + part("diarize", str(diarize).lower())
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    with open(path, "rb") as f:
        body += f.read()
    body += (f"\r\n--{boundary}--\r\n").encode()

    req = urllib.request.Request(api + "/upload", data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())["id"]


def _wait_done(token: str, tid: str, timeout: int, api: str, poll: float, progress_cb) -> dict:
    t0 = time.time()
    last = -1
    stuck_for = 0.0
    while time.time() - t0 < timeout:
        req = urllib.request.Request(api + f"/transcriptions/{tid}/status",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            st = json.loads(r.read().decode())
        status = st.get("status")
        if status == "done":
            if st.get("error"):
                raise RuntimeError(f"job {tid} erro: {st['error']}")
            return st
        if status == "cancelled":
            raise RuntimeError(f"job {tid} terminou como 'cancelled'")
        if status == "error":
            raise RuntimeError(f"job {tid} erro: {st.get('error')}")
        if status == "stuck":
            # 'stuck' costuma ser transitório: há uma janela de race entre o
            # worker marcar 'processing' e se registrar no pool em que o status
            # reporta 'stuck' por engano. Só desiste se persistir (>60s) — e aí
            # confirma no job real antes de falhar (pode ter concluído).
            stuck_for += poll
            if stuck_for >= 60:
                job = _get_job(token, tid, api)
                if job and job.get("status") == "done" and not job.get("error"):
                    return job
                raise RuntimeError(f"job {tid} travado (servidor reiniciou no meio?)")
        else:
            stuck_for = 0.0
            pct = st.get("percent", 0)
            if progress_cb and pct != last:
                progress_cb(pct)
                last = pct
        time.sleep(poll)
    raise TimeoutError(f"job {tid} não concluiu em {timeout}s")


def _get_job(token: str, tid: str, api: str) -> dict | None:
    # GET /transcriptions virou listagem leve (sem segments, text truncado);
    # o job completo vem do /status, que devolve **job quando concluído.
    req = urllib.request.Request(api + f"/transcriptions/{tid}/status",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        st = json.loads(r.read().decode())
    return st if "text" in st else None


def transcribe_file(path: str, model: str = "large-v3", language: str = "pt",
                    diarize: bool = False, api: str = API, token: str | None = None,
                    timeout: int = 1800, poll: float = 2.0, progress_cb=None) -> dict:
    """Transcreve um arquivo de ÁUDIO já em formato suportado pelo /upload.

    Retorna o job completo: {id, text, language, segments (com words), ...}.
    Para vídeos .mov, use transcribe_media().
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    token = token or wait_server(api=api)
    tid = _upload(token, path, model, language, diarize, api)
    st = _wait_done(token, tid, timeout, api, poll, progress_cb)
    # /status no 'done' já devolve **job (com text/segments); get_job é o fallback.
    return _get_job(token, tid, api) or st


def extract_wav(src: str, dst: str, offset: float = 0.0, duration: float | None = None) -> str:
    """Extrai WAV 16 kHz mono via ffmpeg (formato ideal para o Whisper)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if offset > 0:
        cmd += ["-ss", str(offset)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", src, "-ar", "16000", "-ac", "1", dst]
    subprocess.run(cmd, capture_output=True, check=True)
    return dst


def transcribe_span(path: str, start: float, end: float, model: str = "large-v3",
                    language: str = "pt", api: str = API, token: str | None = None,
                    timeout: int = 1800, poll: float = 2.0, progress_cb=None,
                    tmpdir: str | None = None) -> dict:
    """Retranscreve SÓ o trecho [start, end] (segundos) de uma mídia.

    Uso típico: revisão de qualidade — a transcrição saiu num modelo médio e um
    intervalo ficou ruim (words com probability baixa); corta-se o trecho via
    ffmpeg, retranscreve com modelo maior e substituem-se os segments daquele
    intervalo. Os timestamps retornados já vêm REBASEADOS para o arquivo
    original (start somado), prontos para o merge. Dica: dê ~2s de folga de
    cada lado do trecho ruim — contexto melhora o Whisper.
    """
    if end <= start:
        raise ValueError(f"span inválido: start={start} end={end}")
    tmpdir = tmpdir or os.path.dirname(os.path.abspath(path))
    wav = os.path.join(tmpdir, f"_aa_span_{uuid.uuid4().hex[:8]}.wav")
    try:
        extract_wav(path, wav, offset=start, duration=end - start)
        job = transcribe_file(wav, model, language, False, api, token, timeout, poll, progress_cb)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    for seg in job.get("segments") or []:
        seg["start"] = round(seg["start"] + start, 3)
        seg["end"] = round(seg["end"] + start, 3)
        for w in seg.get("words") or []:
            w["start"] = round(w["start"] + start, 3)
            w["end"] = round(w["end"] + start, 3)
    return job


def transcribe_media(path: str, model: str = "large-v3", language: str = "pt",
                     diarize: bool = False, api: str = API, token: str | None = None,
                     timeout: int = 1800, poll: float = 2.0, progress_cb=None,
                     tmpdir: str | None = None) -> dict:
    """Como transcribe_file, mas aceita QUALQUER mídia (ex.: .mov): se a extensão
    não for suportada pelo /upload, extrai um WAV 16 kHz mono temporário antes."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _DIRECT_EXTS:
        return transcribe_file(path, model, language, diarize, api, token, timeout, poll, progress_cb)
    tmpdir = tmpdir or os.path.dirname(os.path.abspath(path))
    wav = os.path.join(tmpdir, f"_aa_{uuid.uuid4().hex[:8]}.wav")
    try:
        extract_wav(path, wav)
        return transcribe_file(wav, model, language, diarize, api, token, timeout, poll, progress_cb)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
