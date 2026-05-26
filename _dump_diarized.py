import sqlite3, json

c = sqlite3.connect(r"F:\claude-projetos\audio-agent\transcriptions\data.db")
cur = c.cursor()
cur.execute("select text, segments from jobs where id='7562d255'")
text, segs_raw = cur.fetchone()
segs = json.loads(segs_raw)
print(f"total segments: {len(segs)}")
speakers = sorted({s.get('speaker','?') for s in segs})
print(f"distinct speakers: {speakers}")

# Render dialogue
lines = []
last_sp = None
buffer = []
for s in segs:
    sp = s.get('speaker', '?')
    txt = s['text'].strip()
    if sp != last_sp:
        if buffer:
            lines.append(f"[{last_sp}] " + " ".join(buffer))
            buffer = []
        last_sp = sp
    buffer.append(txt)
if buffer:
    lines.append(f"[{last_sp}] " + " ".join(buffer))

out = "\n\n".join(lines)
with open(r"F:\claude-projetos\audio-agent\_retest_diarized.txt", "w", encoding="utf-8") as f:
    f.write(out)
print(f"\nsaved {len(out)} chars to _retest_diarized.txt")
print(f"\n--- primeiros 1500 chars ---\n{out[:1500]}")
