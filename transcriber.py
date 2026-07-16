# -*- coding: utf-8 -*-
"""DEPRECADO — engine v1 (openai-whisper) substituída por faster-whisper.

Este módulo era a engine ORIGINAL de transcrição (openai-whisper + monkey-patch
de tqdm para progresso). Foi substituído por `core/services/transcriber.py`
(faster-whisper / CTranslate2). Para não reintroduzir Whisper local — proibido no
hub, pois a GPU é única e dois modelos competindo dão CUDA out of memory (ver
CLAUDE.md) — o código antigo foi removido e este arquivo apenas re-exporta a
engine atual.

Nada deve importar este módulo diretamente. Use `core.services.transcriber`
(dentro do servidor) ou, de qualquer outro script, o cliente HTTP do audio-agent:
`_infra/audio-agent/clients/audio_agent_client.py`.
"""
from core.services.transcriber import (  # noqa: F401
    get_device,
    get_model,
    transcribe_with_progress,
    unload_models,
)
