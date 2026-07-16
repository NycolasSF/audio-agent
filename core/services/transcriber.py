import gc
import os
import threading
import time

import psutil
import torch
from faster_whisper import WhisperModel, decode_audio

# Inicializa contador interno do psutil.cpu_percent (primeira chamada sempre 0.0)
psutil.cpu_percent(interval=None)

_model_cache: dict = {}
_model_lock = threading.Lock()


def get_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _default_compute_type(device: str) -> str:
    """Tipo de cálculo do CTranslate2.

    float16 na GPU = qualidade idêntica ao FP16 do Whisper original, mas no
    engine otimizado. int8 na CPU. Override via WHISPER_COMPUTE_TYPE (ex.:
    int8_float16 para ainda mais velocidade/menos VRAM com perda desprezível).
    """
    env = os.getenv("WHISPER_COMPUTE_TYPE")
    if env:
        return env
    return "float16" if device == "cuda" else "int8"


def get_model(model_name: str, device: str) -> WhisperModel:
    compute_type = _default_compute_type(device)
    key = (model_name, device, compute_type)
    with _model_lock:
        if key not in _model_cache:
            # Numa GPU de VRAM limitada (ex.: 8 GB), manter dois modelos Whisper
            # carregados ao mesmo tempo estoura a memória — base + medium + large
            # empilham e o próximo load dá CUDA out of memory. Por isso mantemos
            # no máximo UM modelo por device na GPU: ao trocar de modelo,
            # descarregamos os antigos da VRAM antes de carregar o novo.
            if device == "cuda":
                stale = [k for k in _model_cache if k[1] == "cuda" and k != key]
                if stale:
                    for k in stale:
                        del _model_cache[k]
                    gc.collect()
                    try:
                        torch.cuda.empty_cache()
                        torch.cuda.ipc_collect()
                    except Exception:
                        pass
                    print(
                        f"[Whisper] Liberados {len(stale)} modelo(s) GPU antigo(s) "
                        f"da VRAM antes de trocar de modelo."
                    )
            print(
                f"[Whisper] Carregando modelo '{model_name}' em {device.upper()} "
                f"({compute_type}) via faster-whisper..."
            )
            # download_root None = cache padrão do HuggingFace (~/.cache).
            # Na 1ª execução baixa o modelo CTranslate2 (medium ~1.5 GB).
            _model_cache[key] = WhisperModel(
                model_name, device=device, compute_type=compute_type
            )
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


# O FeatureExtractor do faster-whisper computa a STFT do áudio INTEIRO de uma
# vez, e o np.fft.rfft faz upcast interno para float64/complex128: um áudio de
# 3h aloca ~6,7 GB de RAM e morre com "Unable to allocate". Transcrever em
# blocos limita o pico a ~1 GB independente da duração.
# ponytail: corte fixo a cada 30 min — palavra exatamente na fronteira pode
# truncar; se incomodar, cortar no silêncio via VAD.
_CHUNK_SECONDS = 30 * 60
_SAMPLE_RATE = 16000

_DEFAULT_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT") or None
# VAD (Silero) remove silêncios antes de transcrever: acelera e corta uma fonte
# extra de alucinação. Default off para reproduzir exatamente o comportamento
# anterior; ligue com WHISPER_VAD_FILTER=true.
_VAD_FILTER = os.getenv("WHISPER_VAD_FILTER", "false").lower() in ("1", "true", "yes")


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

        # Anti-alucinação: defaults explícitos contra cascata em silêncios.
        # condition_on_previous_text=False impede que uma alucinação vire
        # contexto do próximo segmento (causa raiz de "謝謝", "Courtdor 5",
        # blocos de "..."). Temperature cortada em 0.6 elimina a cauda alta
        # do fallback onde nascem variações degeneradas.
        prompt = initial_prompt if initial_prompt is not None else _DEFAULT_INITIAL_PROMPT

        audio = decode_audio(file_path, sampling_rate=_SAMPLE_RATE)
        total = len(audio) / _SAMPLE_RATE
        chunk_samples = _CHUNK_SECONDS * _SAMPLE_RATE

        out_segments = []
        text_parts = []
        lang = language
        for chunk_start in range(0, len(audio), chunk_samples):
            offset = chunk_start / _SAMPLE_RATE
            # segments_gen é um gerador preguiçoso: a transcrição roda conforme
            # iteramos. Progresso = posição absoluta (offset + segment.end)
            # contra a duração total; throttle e cancelamento entre segmentos.
            segments_gen, info = model.transcribe(
                audio[chunk_start : chunk_start + chunk_samples],
                language=lang,
                word_timestamps=True,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                temperature=[0.0, 0.2, 0.4, 0.6],
                initial_prompt=prompt,
                vad_filter=_VAD_FILTER,
            )
            # Detecta o idioma no 1º bloco e fixa nos demais, para não trocar
            # de língua no meio da transcrição.
            if lang is None:
                lang = info.language

            for seg in segments_gen:
                if device == "cuda":
                    _throttle_gpu(gpu_limit)
                else:
                    _throttle_cpu(cpu_limit)

                text_parts.append(seg.text)
                out_segments.append(
                    {
                        "start": round(seg.start + offset, 3),
                        "end": round(seg.end + offset, 3),
                        "text": seg.text.strip(),
                        "words": [
                            {
                                "word": w.word,
                                "start": round(w.start + offset, 3),
                                "end": round(w.end + offset, 3),
                                "probability": round(float(w.probability), 4),
                            }
                            for w in (seg.words or [])
                        ],
                    }
                )

                if progress_cb and total:
                    pct = int(min((seg.end + offset) / total * 100, 99))
                    progress_cb(pct)

        if progress_cb:
            progress_cb(99)

        return {
            "success": True,
            "text": "".join(text_parts).strip(),
            "language": lang or "?",
            "segments": out_segments,
        }
    except Exception as e:
        # Cancelamento pelo usuário deve subir intacto para o worker tratar
        # (não virar job em erro). Detecta por nome para evitar import circular.
        if type(e).__name__ == "CancelledTranscriptionError":
            raise
        msg = str(e)
        # Um CUDA out of memory envenena o contexto do CTranslate2: sem limpar a
        # VRAM, TODA transcrição seguinte falha em cascata até o servidor ser
        # reiniciado na mão. Aqui auto-recuperamos — descarregamos os modelos e
        # liberamos a GPU — para que o próximo job volte a funcionar sozinho.
        low = msg.lower()
        if "out of memory" in low or "cuda failed" in low or "cublas" in low or "cudnn" in low:
            print(f"[Whisper] OOM/erro CUDA detectado — liberando VRAM para recuperar: {msg[:120]}")
            try:
                unload_models()
            except Exception:
                pass
        return {"success": False, "text": "", "segments": [], "error": msg}
