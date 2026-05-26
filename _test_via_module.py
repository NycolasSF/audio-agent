"""Usa o mesmo modulo que o worker usa, para reproduzir o 404."""
import os, time
# proxy envs?
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY","http_proxy","https_proxy"):
    if k in os.environ:
        print(f"ENV {k}={os.environ[k]}")
print("--- chamando diarize() via core.services.diarizer ---")
from core.services.diarizer import diarize
t0 = time.time()
try:
    segs = diarize(r"recordings\upload_ea6c06b6.m4a")
    print(f"OK em {time.time()-t0:.1f}s, {len(segs)} segmentos")
    print("primeiros 3:", segs[:3])
except Exception as e:
    print(f"FALHOU em {time.time()-t0:.1f}s: {type(e).__name__}: {e}")
    if hasattr(e, "response"):
        print("response body:", e.response.text[:500])
