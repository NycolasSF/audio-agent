"""
Viewer interativo do banco de dados do AudioAgent.

Uso:
    python scripts/view_db.py           # atualiza a cada 3s
    python scripts/view_db.py --once    # exibe uma vez e sai
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "transcriptions" / "data.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_dur(s) -> str:
    if s is None:
        return "-"
    s = int(float(s))
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s" if m else f"{s}s"


def _short(text: str | None, n: int = 40) -> str:
    if not text:
        return "-"
    text = text.strip().replace("\n", " ")
    # Sanitize to ASCII-safe for legacy Windows terminals
    text = text.encode("cp1252", errors="replace").decode("cp1252")
    return text[:n] + "..." if len(text) > n else text


def _status_style(s: str) -> str:
    return {
        "done":       "[green]done[/]",
        "processing": "[yellow]processing[/]",
        "pending":    "[cyan]pending[/]",
        "error":      "[red]error[/]",
    }.get(s, s)


def render(console) -> None:
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    from rich.columns import Columns

    if not DB_PATH.exists():
        console.print(f"[red]Banco não encontrado:[/] {DB_PATH}")
        return

    conn = get_conn()
    try:
        # ── Jobs ──────────────────────────────────────────────────────────────
        rows = conn.execute("""
            SELECT id, status, title, source, model, device, duration,
                   percent, error, created_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT 30
        """).fetchall()

        jobs_table = Table(
            title="JOBS (ultimos 30)",
            box=box.ROUNDED,
            show_lines=False,
            expand=True,
            header_style="bold cyan",
        )
        jobs_table.add_column("ID", style="dim", width=9)
        jobs_table.add_column("Status", width=11)
        jobs_table.add_column("Titulo / Fonte", max_width=38)
        jobs_table.add_column("Modelo", width=10)
        jobs_table.add_column("Device", width=6)
        jobs_table.add_column("Dur.", width=7)
        jobs_table.add_column("%", width=5)
        jobs_table.add_column("Criado", width=17)

        for r in rows:
            pct = f"{r['percent']}%" if r["status"] == "processing" else ""
            title = r["title"] or r["source"] or r["id"]
            created = (r["created_at"] or "")[:16]
            jobs_table.add_row(
                r["id"][:8],
                _status_style(r["status"]),
                _short(title, 38),
                r["model"] or "—",
                (r["device"] or "—").lower(),
                _fmt_dur(r["duration"]),
                pct,
                created,
            )

        # ── Benchmarks ────────────────────────────────────────────────────────
        brows = conn.execute("""
            SELECT b.job_id, b.model, b.device,
                   b.audio_duration, b.transcription_time, b.rtf, b.created_at
            FROM benchmarks b
            ORDER BY b.created_at DESC
            LIMIT 10
        """).fetchall()

        bench_table = Table(
            title="BENCHMARKS (ultimos 10)",
            box=box.ROUNDED,
            show_lines=False,
            header_style="bold magenta",
        )
        bench_table.add_column("Job", style="dim", width=9)
        bench_table.add_column("Modelo", width=10)
        bench_table.add_column("Device", width=7)
        bench_table.add_column("Audio", width=8)
        bench_table.add_column("Tempo", width=8)
        bench_table.add_column("RTF", width=7)
        bench_table.add_column("Criado", width=17)

        for b in brows:
            rtf = b["rtf"]
            rtf_style = "green" if rtf and rtf < 1 else ("yellow" if rtf and rtf < 3 else "red")
            bench_table.add_row(
                (b["job_id"] or "")[:8],
                b["model"] or "—",
                (b["device"] or "—").lower(),
                _fmt_dur(b["audio_duration"]),
                _fmt_dur(b["transcription_time"]),
                f"[{rtf_style}]{rtf:.2f}x[/]" if rtf else "—",
                (b["created_at"] or "")[:16],
            )

        # ── Queue ─────────────────────────────────────────────────────────────
        queue_rows = conn.execute("""
            SELECT q.job_id, j.model, j.source, q.created_at
            FROM job_queue q
            JOIN jobs j ON j.id = q.job_id
            ORDER BY q.id
        """).fetchall()

        queue_text = Text()
        if queue_rows:
            queue_text.append(f"  {len(queue_rows)} job(s) na fila:\n", style="yellow bold")
            for q in queue_rows[:8]:  # limit display
                queue_text.append(f"  - {q['job_id'][:8]}  {_short(q['source'], 28)}  [{q['model']}]\n")
            if len(queue_rows) > 8:
                queue_text.append(f"  ... e mais {len(queue_rows) - 8}\n", style="dim")
        else:
            queue_text.append("  Fila vazia", style="dim")

        queue_panel = Panel(queue_text, title="[bold]Fila[/]", expand=False)

        # ── Users ─────────────────────────────────────────────────────────────
        urows = conn.execute("""
            SELECT u.id, u.email, u.name, u.quota_minutes,
                   COALESCE(SUM(um.minutes), 0) AS used_minutes,
                   u.is_admin
            FROM users u
            LEFT JOIN usage_minutes um ON um.user_id = u.id
            GROUP BY u.id
            ORDER BY used_minutes DESC
        """).fetchall()

        users_table = Table(
            title="USUARIOS",
            box=box.ROUNDED,
            show_lines=False,
            header_style="bold blue",
        )
        users_table.add_column("Email", max_width=32)
        users_table.add_column("Nome", max_width=20)
        users_table.add_column("Usado (min)", width=12)
        users_table.add_column("Cota (min)", width=11)
        users_table.add_column("Admin", width=6)

        for u in urows:
            quota = u["quota_minutes"]
            used = u["used_minutes"] or 0
            quota_str = "∞" if quota == -1 else f"{quota:.0f}"
            admin = "[green]sim[/]" if u["is_admin"] else ""
            users_table.add_row(
                _short(u["email"], 32),
                _short(u["name"], 20) if u["name"] else "-",
                f"{used:.1f}",
                quota_str,
                admin,
            )

    finally:
        conn.close()

    console.clear()
    console.print()
    console.print(jobs_table)
    console.print()
    console.print(Columns([queue_panel, bench_table], equal=False, expand=True))
    if urows:
        console.print()
        console.print(users_table)
    console.print(f"\n  [dim]DB: {DB_PATH}  |  {time.strftime('%H:%M:%S')}[/]")


def main():
    parser = argparse.ArgumentParser(description="AudioAgent DB Viewer")
    parser.add_argument("--once", action="store_true", help="Exibir uma vez e sair")
    args = parser.parse_args()

    try:
        from rich.console import Console
    except ImportError:
        print("Instale rich:  pip install rich")
        return

    console = Console()

    if args.once:
        render(console)
        return

    console.print("[dim]Atualizando a cada 3s… Ctrl+C para sair[/]")
    try:
        while True:
            render(console)
            time.sleep(3)
    except KeyboardInterrupt:
        console.print("\n[dim]Saindo.[/]")


if __name__ == "__main__":
    main()
