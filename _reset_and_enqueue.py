import sqlite3, datetime

NOW = datetime.datetime.now(datetime.UTC).isoformat()
c = sqlite3.connect(r"F:\claude-projetos\_infra\transcritor\transcriptions\data.db")
cur = c.cursor()
cur.execute("update jobs set status='pending', percent=0, updated_at=? where id='7562d255'", (NOW,))
cur.execute("delete from job_queue where job_id='7562d255'")
cur.execute("insert into job_queue (job_id, created_at) values ('7562d255', ?)", (NOW,))
c.commit()
print("reset+requeued 7562d255")
