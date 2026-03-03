# 🚀 AudioAgent — Release v2 Completa

---

# 1️⃣ Estrutura de Pastas Oficial (Monólito Modular - Monorepo)

```
audio-agent/
│
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/
│   │   └── ws/
│   │
│   └── worker/
│       └── worker.py
│
├── core/
│   ├── domain/
│   ├── services/
│   └── settings.py
│
├── infra/
│   ├── repo_sqlite.py
│   ├── queue_sqlite.py
│   ├── storage_local.py
│   └── benchmark.py
│
├── static/
│   └── index.html
│
├── transcriptions/
│   └── data.db
│
├── release-bancodados.md
└── README.md
```

## Princípios

- API não executa transcrição
- Worker executa Whisper
- Core não depende de SQLite ou FastAPI
- Infra implementa persistência e storage
- Sistema pronto para Postgres e S3 futuramente

---

# 2️⃣ Contratos de Interface (Preparação para Cloud)

## Interface Repo

```python
class TranscriptionRepo:
    def create_job(self, data: dict): ...
    def update_progress(self, job_id: str, progress: int): ...
    def mark_processing(self, job_id: str): ...
    def mark_done(self, job_id: str, result: dict): ...
    def mark_error(self, job_id: str, error: str): ...
    def get_job(self, job_id: str): ...
    def list_jobs(self, limit: int, offset: int): ...
```

## Interface Queue

```python
class JobQueue:
    def enqueue(self, job_id: str): ...
    def next_job(self): ...
```

## Interface Storage

```python
class Storage:
    def save_audio(self, file): ...
    def save_export(self, job_id: str, content: bytes, ext: str): ...
```

Essas interfaces permitem trocar SQLite → Postgres e Storage Local → S3 sem alterar API ou Worker.

---

# 3️⃣ Worker Separado (Exemplo Simplificado)

```python
while True:
    job = queue.next_job()
    if not job:
        sleep(1)
        continue

    repo.mark_processing(job.id)

    start_time = now()

    try:
        result = transcribe_with_progress(
            job.file,
            model=job.model,
            progress_cb=lambda p: repo.update_progress(job.id, p)
        )

        repo.mark_done(job.id, result)

        rtf = (now() - start_time) / job.duration
        benchmark.save(job.model, job.device, job.duration, rtf)

    except Exception as e:
        repo.mark_error(job.id, str(e))
```

Worker roda isolado da API.

---

# 4️⃣ Roadmap v3 (Escala e SaaS)

## Fase 1 — Local Estável

- SQLite v2 ativo
- Worker separado
- Modelos limitados: small, medium, large-v3
- Benchmark RTF salvo
- Diarização ativa
- Speaker identification opt-in

## Fase 2 — Multiusuário

Adicionar tabelas:
- users
- usage_minutes
- billing

Adicionar autenticação JWT.

## Fase 3 — Migração Cloud

Substituições diretas:

| Local | Cloud |
|-------|-------|
| SQLite | Postgres |
| Storage local | S3 |
| Queue SQLite | Redis/SQS |
| Worker local | Container GPU |

Nenhuma mudança no frontend necessária.

## Fase 4 — Escala Horizontal

- API stateless
- Workers GPU auto-escaláveis
- Redis PubSub para progresso em tempo real
- Monitoramento de fila

---

# 🎙️ Falantes (Diarização + Identificação Opt-In)

## Schema Adicional

### speaker_profiles

```sql
CREATE TABLE speaker_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at TEXT
);
```

### speaker_embeddings

```sql
CREATE TABLE speaker_embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  speaker_id INTEGER,
  embedding BLOB,
  model TEXT,
  created_at TEXT
);
```

### segments ganha:

- speaker_label
- speaker_id

Pipeline:
1. Diarização gera speaker_label
2. Whisper transcreve
3. Se perfil existir → comparar embedding
4. Se similaridade > limiar → atribuir speaker_id

---

# 📊 Benchmark Oficial (RTF)

## Fórmula

RTF = tempo_transcrição / duração_áudio

Tempo estimado = duração × RTF

## Modelos Permitidos

- small
- medium
- large-v3

Qualquer outro modelo retorna erro 400.

---

# 🏁 Resultado Final

O AudioAgent passa a ser:

- Modular
- Persistente
- Escalável
- Pronto para SaaS
- Preparado para GPU cluster
- Preparado para RAG futuro
- Seguro quanto à identificação vocal (opt-in)

---

Fim da Release v2

