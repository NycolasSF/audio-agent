"""One-time migration: transcriptions/data.json → transcriptions/data.db

Run from the project root:
    python scripts/migrate_json_to_sqlite.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.db import get_connection, init_db

DATA_JSON = Path("transcriptions/data.json")


def migrate() -> None:
    if not DATA_JSON.exists():
        print("Nenhum data.json encontrado — nada para migrar.")
        return

    try:
        data: dict = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Erro ao ler data.json: {e}")
        sys.exit(1)

    init_db()

    conn = get_connection()
    migrated = 0
    skipped = 0
    try:
        for job_id, entry in data.items():
            has_error = bool(entry.get("error"))
            status = "error" if has_error else "done"
            percent = 0 if has_error else 100

            segments = entry.get("segments", [])
            segments_json = json.dumps(segments, ensure_ascii=False)

            # Use timestamp as created_at (best approximation)
            created_at = entry.get("timestamp", datetime.now().isoformat())

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs
                      (id, status, title, source, file_path, model, device,
                       timestamp, duration, percent, text, language, segments,
                       error, created_at, updated_at)
                    VALUES
                      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        status,
                        entry.get("title", ""),
                        entry.get("source", ""),
                        entry.get("file", ""),          # data.json uses "file", schema uses "file_path"
                        entry.get("model", "base"),
                        entry.get("device", "cpu"),
                        entry.get("timestamp", ""),
                        entry.get("duration", 0.0),
                        percent,
                        entry.get("text") or None,
                        entry.get("language") or None,
                        segments_json,
                        entry.get("error") or None,
                        created_at,
                        created_at,
                    ),
                )
                migrated += 1
            except Exception as e:
                print(f"  Aviso: falha ao migrar {job_id}: {e}")
                skipped += 1

        conn.commit()
    finally:
        conn.close()

    print(f"Migração concluída: {migrated} registros inseridos, {skipped} ignorados.")
    print(f"Banco de dados: {Path('transcriptions/data.db').resolve()}")


if __name__ == "__main__":
    migrate()
