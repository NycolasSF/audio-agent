"""
Dashboard ao vivo — lê SQLite + psutil + torch.cuda.
Roda em terminal separado sem mexer no servidor.

Uso:
    python scripts/dashboard_live.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "transcriptions" / "data.db"
START_TS = time.time()


def _fmt_dur(s) -> str:
    if s is None:
        return "-"
    s = int(float(s))
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s" if m else f"{s}s"


def _bar(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, float(pct or 0)))
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _fmt_bytes(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f}GB"
    return f"{n / (1 << 20):.0f}MB"


def _safe(text: str | None, n: int = 42) -> str:
    if not text:
        return "-"
    text = text.strip().replace("\n", " ")
    text = text.encode("cp1252", errors="replace").decode("cp1252")
    return text[:n] + "..." if len(text) > n else text


def _get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _sys_metrics():
    cpu_pct = ram_used = ram_total = None
    gpu_util = gpu_mem_used = gpu_mem_total = gpu_name = None
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ram_used = vm.used
        ram_total = vm.total
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            gpu_util = torch.cuda.utilization(0)
            gpu_mem_used = torch.cuda.memory_allocated(0)
            gpu_mem_total = torch.cuda.get_device_properties(0).total_memory
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    # Fallback: nvidia-smi (works even without CUDA Python bindings)
    if gpu_util is None:
        try:
            import subprocess
            out = subprocess.check_output(
                ["nvidia-smi",
                 "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                timeout=2, stderr=subprocess.DEVNULL
            ).decode().strip().splitlines()[0]
            parts = [p.strip() for p in out.split(",")]
            gpu_name = parts[0]
            gpu_util = int(parts[1])
            gpu_mem_used = int(parts[2]) * (1 << 20)   # MiB → bytes
            gpu_mem_total = int(parts[3]) * (1 << 20)
        except Exception:
            pass

    return cpu_pct, ram_used, ram_total, gpu_util, gpu_mem_used, gpu_mem_total, gpu_name


def _build(console_width: int):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    cpu_pct, ram_used, ram_total, gpu_util, gpu_mem_used, gpu_mem_total, gpu_name = _sys_metrics()

    conn = _get_db()
    processing = []
    pending_count = 0
    recent_done = []
    if conn:
        try:
            rows = conn.execute(
                "SELECT id, status, title, source, model, device, duration, percent "
                "FROM jobs ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            for r in rows:
                if r["status"] == "processing":
                    processing.append(r)
                elif r["status"] == "pending":
                    pending_count += 1
                elif r["status"] == "done" and len(recent_done) < 3:
                    recent_done.append(r)
        except Exception:
            pass
        finally:
            conn.close()

    uptime = _fmt_dur(time.time() - START_TS)
    now = time.strftime("%H:%M:%S")
    device_label = gpu_name or "CPU"

    # ── Header ──────────────────────────────────────────────────────────────
    hdr = Text(justify="center")
    hdr.append("claude.audio", style="bold white")
    hdr.append("  |  ", style="dim")
    hdr.append("localhost:8020", style="cyan")
    hdr.append("  |  ", style="dim")
    hdr.append(_safe(device_label, 30), style="green")
    hdr.append("  |  up ", style="dim")
    hdr.append(uptime, style="yellow")
    header = Panel(hdr, box=box.ROUNDED, border_style="dim", height=3)

    # ── System panel ────────────────────────────────────────────────────────
    sys_t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    sys_t.add_column(style="dim", width=5)
    sys_t.add_column()

    if cpu_pct is not None:
        sys_t.add_row("CPU", f"[cyan]{_bar(cpu_pct, 16)}[/] [bold]{cpu_pct:4.0f}%[/]")
    else:
        sys_t.add_row("CPU", "[dim]n/a[/]")

    if ram_used is not None:
        pct = ram_used / ram_total * 100
        sys_t.add_row("RAM", f"[cyan]{_bar(pct, 16)}[/] [bold]{_fmt_bytes(ram_used)}/{_fmt_bytes(ram_total)}[/]")
    else:
        sys_t.add_row("RAM", "[dim]n/a[/]")

    if gpu_util is not None:
        sys_t.add_row("GPU", f"[{'red' if gpu_util > 80 else 'cyan'}]{_bar(gpu_util, 16)}[/] [bold]{gpu_util:3d}%[/]")
    else:
        sys_t.add_row("GPU", "[dim]n/a[/]")

    if gpu_mem_used is not None:
        gm_pct = gpu_mem_used / gpu_mem_total * 100
        sys_t.add_row("VRAM", f"[cyan]{_bar(gm_pct, 16)}[/] [bold]{_fmt_bytes(gpu_mem_used)}/{_fmt_bytes(gpu_mem_total)}[/]")
    else:
        sys_t.add_row("VRAM", "[dim]n/a[/]")

    sys_panel = Panel(sys_t, title="[bold]Sistema[/]", box=box.ROUNDED, border_style="dim")

    # ── Jobs panel ──────────────────────────────────────────────────────────
    job_t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    job_t.add_column(style="dim", width=9)
    job_t.add_column()

    if processing:
        for r in processing:
            pct = r["percent"] or 0
            src = r["title"] or r["source"] or r["id"]
            dev = (r["device"] or "cpu").lower()
            dev_color = "green" if dev == "cuda" else "yellow"
            job_t.add_row(
                f"[bold cyan]{r['id'][:8]}[/]",
                f"[white]{_safe(src, 38)}[/]"
            )
            job_t.add_row(
                "",
                f"[cyan]{_bar(pct, 24)}[/] [bold]{pct:3d}%[/]  [{dev_color}]{dev}[/]  [dim]{r['model']}  {_fmt_dur(r['duration'])}[/]"
            )
            job_t.add_row("", "")
    else:
        job_t.add_row("", "[dim]Nenhuma transcricao em andamento[/]")
        job_t.add_row("", "")

    # Queue count
    if pending_count:
        job_t.add_row("", f"[yellow]Fila: {pending_count} pendentes[/]")
    else:
        job_t.add_row("", "[dim]Fila vazia[/]")

    # Recent done
    if recent_done:
        job_t.add_row("", "")
        job_t.add_row("", "[dim]-- Concluidos recentes --[/]")
        for r in recent_done:
            src = r["title"] or r["source"] or r["id"]
            job_t.add_row(
                f"[dim]{r['id'][:8]}[/]",
                f"[dim]{_safe(src, 38)}  {_fmt_dur(r['duration'])}[/]"
            )

    jobs_panel = Panel(job_t, title="[bold]Transcricoes[/]", box=box.ROUNDED, border_style="dim")

    footer = Text(f"  {now}  |  Ctrl+C sair  |  DB: {DB_PATH.name}", style="dim")

    layout = Layout()
    layout.split_column(
        Layout(header, size=3, name="header"),
        Layout(name="body"),
        Layout(footer, size=1, name="footer"),
    )
    layout["body"].split_row(
        Layout(sys_panel, ratio=2, name="system"),
        Layout(jobs_panel, ratio=3, name="jobs"),
    )
    return layout


def main():
    try:
        from rich.live import Live
        from rich.console import Console
    except ImportError:
        print("pip install rich")
        sys.exit(1)

    console = Console()
    # Warm up cpu_percent (first call returns 0.0)
    try:
        import psutil
        psutil.cpu_percent(interval=None)
    except Exception:
        pass

    try:
        with Live(console=console, refresh_per_second=2, screen=True) as live:
            while True:
                try:
                    live.update(_build(console.width))
                except Exception as e:
                    from rich.text import Text
                    live.update(Text(f"Erro ao renderizar: {e}", style="red"))
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
