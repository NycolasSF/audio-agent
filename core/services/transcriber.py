import gc
import importlib
import os
import threading
import time

import psutil
import tqdm as _tqdm_pkg
import torch
import whisper

# Inicializa contador interno do psutil.cpu_percent (primeira chamada sempre 0.0)
psutil.cpu_percent(interval=None)

_wt = importlib.import_module("whisper.transcribe")

_model_cache: dict = {}
_model_lock = threading.Lock()


def get_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_model(model_name: str, device: str):
    key = (model_name, device)
    with _model_lock:
        if key not in _model_cache:
            print(f"[Whisper] Carregando modelo '{model_name}' em {device.upper()}...")
            _model_cache[key] = whisper.load_model(model_name, device=device)
            print(f"[Whisper] Pronto.")
        return _model_cache[key]


def unload_models() -> None:
    """Libera todos os modelos Whisper da memória/VRAM.

    Próxima chamada a ``get_model`` recarrega do disco.
    """
    with _model_lock:
        if not _model_cache:
            return
        count = len(_model_cache)
        _model_cache.clear()
    print(f"[Whisper] Descarregado(s) {count} modelo(s) da memória.")
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception:
            pass


def _throttle_gpu(limit_pct: int) -> None:
    """Dorme entre segmentos quando a GPU ultrapassar o limite de utilização."""
    if not torch.cuda.is_available():
        return
    try:
        util = torch.cuda.utilization()
        if util > limit_pct:
            # Proporcional ao overshoot: cada 10% acima do limite = ~50ms de espera
            sleep_s = (util - limit_pct) / 100 * 0.5
            time.sleep(sleep_s)
    except Exception:
        pass


def _throttle_cpu(limit_pct: int) -> None:
    """Dorme entre segmentos quando a CPU global ultrapassar o limite.

    Espelha _throttle_gpu para o caso de múltiplos CPU_WORKERS rodando lote
    grande. interval=None usa o último snapshot do psutil (chamada barata).
    """
    try:
        util = psutil.cpu_percent(interval=None)
        if util > limit_pct:
            sleep_s = (util - limit_pct) / 100 * 0.5
            time.sleep(sleep_s)
    except Exception:
        pass


_DEFAULT_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT") or None


def transcribe_with_progress(
    file_path: str,
    model_name: str = "base",
    device: str = "cpu",
    progress_cb=None,
    language: str | None = None,
    gpu_limit: int = 70,
    cpu_limit: int = 100,
    initial_prompt: str | None = None,
) -> dict:
    if not os.path.exists(file_path):
        return {"success": False, "text": "", "segments": [], "error": "Arquivo não encontrado"}

    try:
        model = get_model(model_name, device)
        original_tqdm_module = _wt.tqdm
        _device = device

        class _ProgressTqdm(_tqdm_pkg.tqdm):
            def update(self, n=1):
                super().update(n)
                if _device == "cuda":
                    _throttle_gpu(gpu_limit)
                else:
                    _throttle_cpu(cpu_limit)
                if progress_cb and self.total:
                    pct = int(min(self.n / self.total * 100, 99))
                    progress_cb(pct)

        class _TqdmProxy:
            tqdm = _ProgressTqdm

        _wt.tqdm = _TqdmProxy()
        try:
            # Anti-alucinação: defaults explícitos contra cascata em silêncios.
            # condition_on_previous_text=False impede que uma alucinação vire
            # contexto do próximo segmento (causa raiz de "謝謝", "Courtdor 5",
            # blocos de "..."). Temperature cortada em 0.6 elimina a cauda alta
            # do fallback onde nascem variações degeneradas.
            opts = {
                "verbose": False,
                "word_timestamps": True,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.6,
                "logprob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
                "temperature": (0.0, 0.2, 0.4, 0.6),
            }
            if language:
                opts["language"] = language
            prompt = initial_prompt if initial_prompt is not None else _DEFAULT_INITIAL_PROMPT
            if prompt:
                opts["initial_prompt"] = prompt
            result = model.transcribe(file_path, **opts)
        finally:
            _wt.tqdm = original_tqdm_module

        return {
            "success": True,
            "text": result["text"].strip(),
            "language": result.get("language", "?"),
            "segments": [
                {
                    "start": round(s["start"], 3),
                    "end": round(s["end"], 3),
                    "text": s["text"].strip(),
                    "words": [
                        {
                            "word": w["word"],
                            "start": round(w["start"], 3),
                            "end": round(w["end"], 3),
                            "probability": round(float(w.get("probability", 1.0)), 4),
                        }
                        for w in s.get("words", [])
                    ],
                }
                for s in result.get("segments", [])
            ],
        }
    except Exception as e:
        return {"success": False, "text": "", "segments": [], "error": str(e)}
