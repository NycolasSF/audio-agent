import sqlite3

c = sqlite3.connect(r"F:\claude-projetos\audio-agent\transcriptions\data.db")
cur = c.cursor()
cur.execute("""
    select id, status, diarize, model, duration, length(coalesce(text,'')), error, created_at, updated_at
    from jobs
    where created_at like '2026-05-18%'
    order by created_at desc
""")
for r in cur.fetchall():
    print(r)
