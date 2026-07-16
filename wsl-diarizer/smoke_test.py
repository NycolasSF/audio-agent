"""Smoke test 3D-Speaker no WSL2 (Linux + GPU).

Roda o pipeline ModelScope contra os modelos locais e confirma que NAO segfaulta
como aconteceu no Windows.
"""
import os
import sys
import time

CACHE = "/mnt/f/claude-projetos/_infra/transcritor/models/modelscope"
MODEL = f"{CACHE}/iic/speech_campplus_speaker-diarization_common"
WAV = f"{MODEL}/examples/2speakers_example.wav"

os.environ["MODELSCOPE_CACHE"] = CACHE
os.environ["DISABLE_NEW_VERSION"] = "true"
os.environ["MODELSCOPE_LOG_LEVEL"] = "40"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

print(f"[smoke] cache  = {CACHE}")
print(f"[smoke] model  = {MODEL}")
print(f"[smoke] sample = {WAV}")
print(f"[smoke] python = {sys.version.split()[0]}")

import torch
print(f"[smoke] torch  = {torch.__version__}  cuda={torch.cuda.is_available()}")

from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks

t0 = time.time()
print("[smoke] building pipeline...")
p = pipeline(task=Tasks.speaker_diarization, model=MODEL)
print(f"[smoke] pipeline built in {time.time()-t0:.2f}s")

t1 = time.time()
print("[smoke] running inference...")
result = p(WAV)
elapsed = time.time() - t1
print(f"[smoke] inference done in {elapsed:.2f}s")

print(f"[smoke] result type: {type(result)}")
print(f"[smoke] result keys: {list(result.keys()) if isinstance(result, dict) else 'n/a'}")
print(f"[smoke] result: {result}")
print("[smoke] OK")
