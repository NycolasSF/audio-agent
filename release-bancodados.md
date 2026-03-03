# Release: Migração para SQLite

## Motivação

O sistema atualmente persiste todas as transcrições em `transcriptions/data.json`. Cada operação — salvar, editar título, deletar — lê e reescreve o arquivo inteiro. Isso gera três problemas sérios em escala:

1. **Performance**: com 2000 transcrições (texto + segmentos), o arquivo pode ter 20–50 MB relidos e reescritos em toda operação, incluindo o polling de status a cada 2 segundos.
2. **Race condition**: o executor tem `max_workers=2`. Se duas transcrições terminam ao mesmo tempo, a segunda sobrescreve os dados da primeira silenciosamente.
3. **Carregamento inicial**: `GET /transcriptions` retorna todos os itens de uma vez; o frontend renderiza 2000 `<tr>` sem paginação, congelando o browser.

**Requisitos de instalação: nenhum.** `sqlite3` já faz parte da biblioteca padrão do Python — nada muda no `requirements.txt`.

---

## Mudanças em `main.py`

### 1. Substituir `TRANSCRIPTIONS_FILE` por `_get_db()`

```python
import sqlite3

DB_PATH = Path("transcriptions/data.db")

def _get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # leituras concorrentes sem bloquear escrita
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id        TEXT PRIMARY KEY,
            title     TEXT DEFAULT '',
            text      TEXT DEFAULT '',
            language  TEXT DEFAULT '?',
            segments  TEXT DEFAULT '[]',
            timestamp TEXT,
            duration  REAL DEFAULT 0.0,
            model     TEXT,
            device    TEXT,
            file      TEXT,
            source    TEXT DEFAULT '',
            error     TEXT DEFAULT NULL
        )
    """)
    conn.commit()
    return conn
```

Cada chamada abre sua própria conexão e fecha ao sair do `with` — SQLite serializa escritas automaticamente, eliminando a race condition sem lock explícito.

### 2. Substituir as 4 funções de persistência

| Função antiga | Nova implementação |
|---|---|
| `_load_all()` | removida |
| `_save_all()` | removida |
| `persist_transcription(entry)` | `INSERT OR REPLACE INTO transcriptions VALUES (...)` |
| `remove_transcription(tid)` | `DELETE FROM transcriptions WHERE id = ?` |
| `patch_transcription(tid, **fields)` | `UPDATE transcriptions SET title = ? WHERE id = ?` |

O campo `segments` é serializado como JSON string (`json.dumps`) na escrita e desserializado (`json.loads`) na leitura — mantém a mesma estrutura de dados que o frontend já espera.

### 3. Paginação em `GET /transcriptions`

```python
@app.get("/transcriptions")
async def get_transcriptions(limit: int = 50, offset: int = 0):
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM transcriptions ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    return [dict(r) | {"segments": json.loads(r["segments"])} for r in rows]
```

### 4. `GET /transcriptions/{tid}/status` — query por ID direto

```python
@app.get("/transcriptions/{tid}/status")
async def get_transcription_status(tid: str):
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM transcriptions WHERE id = ?", (tid,)
        ).fetchone()
    if row:
        d = dict(row)
        d["segments"] = json.loads(d["segments"])
        return {"status": "done", **d}
    return JSONResponse({"status": "processing"})
```

### 5. Migração automática do `data.json` existente

Na inicialização do app (antes do `uvicorn.run`), verificar:

```python
def _migrate_json_to_db():
    json_path = Path("transcriptions/data.json")
    if not json_path.exists() or DB_PATH.exists():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    with _get_db() as conn:
        for entry in data.values():
            conn.execute(
                "INSERT OR IGNORE INTO transcriptions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry.get("id"), entry.get("title",""), entry.get("text",""),
                 entry.get("language","?"), json.dumps(entry.get("segments",[])),
                 entry.get("timestamp"), entry.get("duration",0.0),
                 entry.get("model"), entry.get("device"),
                 entry.get("file"), entry.get("source",""), entry.get("error"))
            )
        conn.commit()
    json_path.rename(json_path.with_suffix(".json.bak"))
    print(f"[Migração] {len(data)} transcrições migradas para SQLite. Backup: data.json.bak")
```

---

## Mudanças em `static/index.html`

### `loadHistory()` — carregamento paginado

```js
let historyOffset = 0;
const HISTORY_PAGE = 50;

async function loadHistory() {
    try {
        const r = await fetch(`/transcriptions?limit=${HISTORY_PAGE}&offset=${historyOffset}`);
        if (!r.ok) return;
        const items = await r.json();
        items.forEach(item => {
            createRow(item);
            completeRow(item, item.title || autoTitle(item.text, item.timestamp));
        });
        historyOffset += items.length;
        if (items.length === HISTORY_PAGE) showLoadMoreButton();
    } catch (e) {
        console.warn("history error", e);
    }
}
```

Adicionar botão "Carregar mais" ao final da lista, visível apenas quando há mais páginas. Ao clicar, chama `loadHistory()` com `offset` já incrementado.

---

## Checklist de verificação

- [ ] `python main.py` sobe sem erro; `transcriptions/data.db` é criado automaticamente
- [ ] Gravar e transcrever → card aparece normalmente na tabela
- [ ] Recarregar a página → histórico carrega (primeiros 50 registros)
- [ ] Clicar "Carregar mais" → próxima página de 50 aparece
- [ ] Editar título → persiste após recarregar
- [ ] Excluir registro → removido do banco e da tabela
- [ ] Se `data.json` existia → `data.json.bak` criado e dados migrados integralmente
- [ ] Dois uploads simultâneos → ambos persistidos sem perda de dados
