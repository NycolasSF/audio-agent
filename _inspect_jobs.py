import sqlite3

c = sqlite3.connect(r"F:\claude-projetos\audio-agent\transcriptions\data.db")
cur = c.cursor()
cur.execute("select id, status, percent, length(text), error from jobs where id in ('e0a50f27','6ab0d70e','7562d255')")
for r in cur.fetchall():
    print(r)
cur.execute("select * from job_queue")
print("queue:", cur.fetchall())
