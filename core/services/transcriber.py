import importlib
import os
import time

import tqdm as _tqdm_pkg
import torch
import whisper

_wt = importlib.import_module("whisper.transcribe")

_model_cache: dict = {}


def get_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_model(model_name: str, device: str):
    key = (model_name, device)
    if key not in _model_cache:
        print(f"[Whisper] Carregando modelo '{model_name}' em {device.upper()}...")
        _model_cache[key] = whisper.load_model(model_name, device=device)
        print(f"[Whisper] Pronto.")
    return _model_cache[key]


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


def transcribe_with_progress(
    file_path: str,
    model_name: str = "base",
    device: str = "cpu",
    progress_cb=None,
    language: str | None = None,
    gpu_limit: int = 70,
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
                if progress_cb and self.total:
                    pct = int(min(self.n / self.total * 100, 99))
                    progress_cb(pct)

        class _TqdmProxy:
            tqdm = _ProgressTqdm

        _wt.tqdm = _TqdmProxy()
        try:
            opts = {"verbose": False}
            if language:
                opts["language"] = language
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
                }
                for s in result.get("segments", [])
            ],
        }
    except Exception as e:
        return {"success": False, "text": "", "segments": [], "error": str(e)}
