import threading
import time

import uvicorn


def _fallback_loop(server: uvicorn.Server) -> None:
    """Keep main thread alive when dashboard is unavailable."""
    try:
        while not server.should_exit:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True


if __name__ == "__main__":
    config = uvicorn.Config(
        "apps.api.main:app",
        host="0.0.0.0",
        port=8020,
        reload=False,
        log_level="warning",        # silencia access logs no painel
        access_log=False,
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    t.start()

    # Aguarda uvicorn inicializar (singletons prontos em apps.api.main startup)
    while not server.started:
        time.sleep(0.05)

    # Importa state DEPOIS do startup — garante que singletons estão inicializados
    from apps.api import state

    try:
        from monitor.dashboard import run_dashboard
        run_dashboard(state, server)
    except KeyboardInterrupt:
        server.should_exit = True
    except Exception as e:
        print(f"[Dashboard] Erro ao iniciar painel: {e}")
        print("[Dashboard] Servidor continua rodando normalmente.")
        _fallback_loop(server)
    finally:
        server.should_exit = True
