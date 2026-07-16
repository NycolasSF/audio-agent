"""Painel read-only — anexa a um AudioAgent que JÁ está rodando.

Lê os dados reais do SQLite compartilhado (modo WAL → leitura concorrente segura,
não trava o servidor) + métricas de sistema locais (CPU/GPU via psutil/nvidia-smi).
NÃO sobe servidor nenhum.

Usado pelo start.bat quando a porta 8020 já está ocupada, para que clicar no
start.bat sempre entregue a visão de background — esteja o servidor recém-subido
ou já de pé em outra janela.

A única seção ausente em relação ao painel embutido é WORKERS (o pool vive na
memória do processo do servidor); transcrições ativas, fila, progresso e GPU
aparecem normalmente.
"""
from __future__ import annotations

import time

from monitor.dashboard import _build


class _AttachedState:
    """State mínimo para _build(): jobs reais do SQLite, métricas locais.
    pool=None → _build cai no try/except e a lista de workers fica vazia."""

    pool = None

    def __init__(self):
        from infra.repo_sqlite import SQLiteRepo
        from core.services.transcriber import get_device

        self.repo = SQLiteRepo()
        self.progress_store = {}          # vazio → _build usa o percent do SQLite
        self.DEVICE = get_device()


def main() -> None:
    from rich.live import Live

    state = _AttachedState()

    device_label = state.DEVICE.upper()
    try:
        import torch
        if torch.cuda.is_available():
            device_label += f" — {torch.cuda.get_device_name(0)}"
    except Exception:
        pass

    start_ts = time.time()

    try:
        with Live(refresh_per_second=2, screen=False) as live:
            while True:
                try:
                    live.update(_build(state, device_label, start_ts))
                except Exception:
                    pass
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
