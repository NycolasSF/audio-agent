import httpx, time

t0 = time.time()
r = httpx.post(
    "http://127.0.0.1:9020/diarize",
    json={"file": "/mnt/f/claude-projetos/audio-agent/recordings/upload_ea6c06b6.m4a", "num_speakers": None},
    timeout=600,
)
print(f"HTTP {r.status_code} in {time.time()-t0:.1f}s")
print("body:", r.text[:500])
