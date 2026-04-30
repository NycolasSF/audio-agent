"""Terminal dashboard for claude.audio — displayed while the server runs.

Completely isolated from the server: any exception here is caught and the
server continues unaffected.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn


def _fmt_bytes(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f} MB"
    return f"{n >> 10} KB"


def _bar(pct: float, width: int = 18) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _fmt_dur(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s"


def _build(state, device_label: str, start_ts: float):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    # ── system metrics ────────────────────────────────────────────────────────
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        proc = psutil.Process(os.getpid())
        ram_used = proc.memory_info().rss
        ram_total = psutil.virtual_memory().total
    except Exception:
        cpu_pct = ram_used = ram_total = None

    gpu_util = gpu_mem_used = gpu_mem_total = None
    try:
        import torch
        if torch.cuda.is_available():
            gpu_util = torch.cuda.utilization(0)
            gpu_mem_used = torch.cuda.memory_allocated(0)
            gpu_mem_total = torch.cuda.get_device_properties(0).total_memory
    except Exception:
        pass

    # ── workers ───────────────────────────────────────────────────────────────
    workers = []
    try:
        for w in state.pool.workers:
            jid = w.current_job_id
            workers.append((w.name, w.device.upper(), jid))
    except Exception:
        pass

    # ── active / pending jobs ─────────────────────────────────────────────────
    active_jobs = []
    pending_count = 0
    try:
        jobs = state.repo.list_jobs(limit=100)
        for j in jobs:
            if j["status"] == "processing":
                pct = state.progress_store.get(j["id"]) or j.get("percent") or 0
                active_jobs.append((j["id"], j.get("source") or j["id"], pct,
                                    j.get("model", "?"), j.get("device", "?")))
            elif j["status"] == "pending":
                pending_count += 1
    except Exception:
        pass

    # ── render ────────────────────────────────────────────────────────────────
    uptime = _fmt_dur(time.time() - start_ts)
    now = datetime.now().strftime("%H:%M:%S")

    # Header
    header = Text(justify="center")
    header.append("🎙  ", style="bold red")
    header.append("claude.audio", style="bold white")
    header.append("  │  ", style="dim")
    header.append("localhost:8020", style="cyan")
    header.append("  │  ", style="dim")
    header.append(device_label, style="green")
    header.append("  │  up ", style="dim")
    header.append(uptime, style="yellow")
    header.append("  │  Ctrl+C sair", style="dim")

    # System panel
    sys_table = Table(box=None, show_header=False, padding=(0, 1))
    sys_table.add_column(style="dim", width=6)
    sys_table.add_column(style="white", width=20)

    if cpu_pct is not None:
        sys_table.add_row("CPU", f"[cyan]{_bar(cpu_pct, 14)}[/] {cpu_pct:4.0f}%")
    if ram_used is not None:
        ram_pct = ram_used / ram_total * 100
        sys_table.add_row("RAM", f"[cyan]{_bar(ram_pct, 14)}[/] {_fmt_bytes(ram_used)}/{_fmt_bytes(ram_total)}")
    if gpu_util is not None:
        sys_table.add_row("GPU", f"[cyan]{_bar(gpu_util, 14)}[/] {gpu_util:4d}%")
    if gpu_mem_used is not None:
        gm_pct = gpu_mem_used / gpu_mem_total * 100
        sys_table.add_row("VRAM", f"[cyan]{_bar(gm_pct, 14)}[/] {_fmt_bytes(gpu_mem_used)}/{_fmt_bytes(gpu_mem_total)}")

    sys_table.add_row("", "")
    sys_table.add_row("[dim]WORKERS[/]", "")
    for wname, wdev, wjob in workers:
        short = wname.replace("Worker-", "")
        dot = "[green]●[/]" if wjob else "[dim]○[/]"
        label = f"[green]{wjob[:8]}[/]" if wjob else "[dim]aguardando[/]"
        sys_table.add_row(f"  {short}", f"{dot} {label}")

    system_panel = Panel(sys_table, title="[bold]Sistema[/]", border_style="dim", box=box.ROUNDED)

    # Jobs panel
    jobs_table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    jobs_table.add_column(style="dim", width=8)
    jobs_table.add_column()

    if active_jobs:
        for jid, src, pct, model, dev in active_jobs:
            short_id = jid[:8]
            short_src = src[-36:] if len(src) > 36 else src
            jobs_table.add_row(
                f"[bold cyan]{short_id}[/]",
                f"[white]{short_src}[/]"
            )
            dev_tag = f"[green]{dev.lower()}[/]" if dev and dev.lower() != "?" else "[dim]cpu[/]"
            jobs_table.add_row(
                "",
                f"[cyan]{_bar(pct, 22)}[/] [bold]{pct:3.0f}%[/]  {dev_tag}  [dim]{model}[/]"
            )
            jobs_table.add_row("", "")
    else:
        jobs_table.add_row("", "[dim]Nenhuma transcrição em andamento[/]")
        jobs_table.add_row("", "")

    if pending_count:
        jobs_table.add_row("", f"[yellow]⏳ {pending_count} na fila[/]")
    else:
        jobs_table.add_row("", "[dim]Fila vazia[/]")

    jobs_panel = Panel(jobs_table, title="[bold]Transcrições[/]", border_style="dim", box=box.ROUNDED)

    # Footer
    footer = Text(f"  {now}", style="dim", justify="left")

    # Assemble layout
    layout = Layout()
    layout.split_column(
        Layout(Panel(header, box=box.ROUNDED, border_style="dim"), size=3, name="header"),
        Layout(name="body"),
        Layout(footer, size=1, name="footer"),
    )
    layout["body"].split_row(
        Layout(system_panel, ratio=2, name="system"),
        Layout(jobs_panel, ratio=3, name="jobs"),
    )
    return layout


def run_dashboard(state, server: "uvicorn.Server") -> None:
    """
    Runs the Rich live dashboard in the calling thread (main thread).
    If anything fails, falls through — server keeps running via caller's fallback.
    """
    from rich.live import Live

    # Build device label once
    device_label = state.DEVICE.upper()
    try:
        import torch
        if torch.cuda.is_available():
            device_label += f" — {torch.cuda.get_device_name(0)}"
    except Exception:
        pass

    start_ts = time.time()

    with Live(refresh_per_second=2, screen=False) as live:
        while not server.should_exit:
            try:
                layout = _build(state, device_label, start_ts)
                live.update(layout)
            except Exception:
                pass
            time.sleep(0.5)
