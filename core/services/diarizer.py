"""Speaker diarization via pyannote.audio (opt-in per job).

Lazy-loads the pipeline on first use so the import cost is zero for jobs
that don't request diarization.  Thread-safe via a module-level lock.
"""
import threading

_lock = threading.Lock()
_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                from pyannote.audio import Pipeline
                import torch
                from core import settings

                auth = settings.HUGGINGFACE_TOKEN or True
                p = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=auth,
                )
                if torch.cuda.is_available():
                    p = p.to(torch.device("cuda"))
                _pipeline = p
    return _pipeline


def diarize(file_path: str) -> list:
    """Run diarization on *file_path*.

    Returns a list of dicts: ``[{start, end, speaker}, ...]``.
    Raises on any error (caller is responsible for try/except).
    """
    result = get_pipeline()(file_path)
    return [
        {"start": round(t.start, 3), "end": round(t.end, 3), "speaker": spk}
        for t, _, spk in result.itertracks(yield_label=True)
    ]


def merge_speaker_labels(whisper_segs: list, diarize_segs: list) -> list:
    """Annotate Whisper segments with the diarization speaker label.

    For each Whisper segment the speaker whose interval has the largest
    overlap is chosen.  Falls back to ``"UNKNOWN"`` if there is no overlap.
    """
    out = []
    for seg in whisper_segs:
        best, best_ov = "UNKNOWN", 0.0
        for d in diarize_segs:
            ov = min(seg["end"], d["end"]) - max(seg["start"], d["start"])
            if ov > best_ov:
                best_ov, best = ov, d["speaker"]
        out.append({**seg, "speaker": best})
    return out
