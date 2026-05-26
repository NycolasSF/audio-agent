import sqlite3, uuid, datetime, os

JOB_ID = uuid.uuid4().hex[:8]
NOW = datetime.datetime.now(datetime.UTC).isoformat()
SRC_AUDIO = r"recordings\upload_ea6c06b6.m4a"
USER_ID = "5c19cf83a3a44748b4c0967bbdf28eb6"

assert os.path.exists(SRC_AUDIO), "audio nao encontrado"

c = sqlite3.connect(r"F:\claude-projetos\audio-agent\transcriptions\data.db")
cur = c.cursor()

cur.execute(
    """
    INSERT INTO jobs (id, status, title, source, file_path, model, timestamp,
                       duration, percent, created_at, updated_at, user_id,
                       diarize, input_language)
    VALUES (?, 'pending', 'retest-diarized', 'upload', ?, 'large', ?,
            521.5, 0, ?, ?, ?, 1, 'pt')
    """,
    (JOB_ID, SRC_AUDIO, NOW, NOW, NOW, USER_ID),
)
cur.execute("INSERT INTO job_queue (job_id, created_at) VALUES (?, ?)", (JOB_ID, NOW))
c.commit()
print(f"enqueued job_id={JOB_ID} (diarize=1)")
