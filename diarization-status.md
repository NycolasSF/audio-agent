# Status da Diarização — Sessão 2026-04-30

## Contexto

O `audio-agent` rodava diarização via `pyannote.audio` (commit `d487e3b`). Tentativa anterior de migrar para **NVIDIA NeMo** falhou no Windows (ver `nemo-windows-issues.md`) — NeMo não suporta Windows nativo.

Esta sessão tentou substituir por **3D-Speaker (Alibaba/ModelScope)** com modo offline, sem telemetria.

## O que foi feito

### 1. Reversão da migração NeMo (✅ concluída)

- Working tree (sem commits) tinha NeMo aplicado.
- Arquivos revertidos para HEAD via `git checkout`:
  - `.env.example`
  - `CLAUDE.md`
  - `README.md`
  - `core/services/diarizer.py`
  - `core/settings.py`
  - `requirements.txt`
- **Mantidas** (não relacionadas ao NeMo, são melhorias de UX):
  - `apps/api/ws/handler.py` — propaga campo `error` no `transcription_complete`
  - `apps/worker/worker.py` — captura mensagem de erro de diarização (não silencia)
  - `infra/repo_sqlite.py` — salva `error` no `mark_done()`
  - `static/index.html` — exibe toast de erro pro usuário
- `nemo_toolkit` desinstalado.
- Deps rebaixadas pelo NeMo restauradas: `protobuf 7.34.1`, `packaging 26.2`, `fsspec 2026.4.0`, `lightning 2.6.1`, `decorator 4.4.2`.

### 2. Reset de senha (✅ concluído)

- Hash bcrypt da senha do usuário `nycolas@gmail.com` foi resetado em `transcriptions/data.db`.
- **Senha temporária:** `audioagent2026` (deve ser trocada pela UI no próximo login).

### 3. Migração para 3D-Speaker (⚠️ bloqueada por segfault no Windows)

#### Código aplicado
- `core/settings.py` — substituído bloco `HUGGINGFACE_TOKEN` por `DIARIZATION_MODEL`, `DIARIZATION_USE_CUDA`, `DIARIZATION_NUM_SPEAKERS`, `MODELSCOPE_CACHE_DIR`.
- `core/services/diarizer.py` — reescrito usando `modelscope.pipelines.pipeline(task='speaker-diarization')`, com env vars para cache local e supressão de telemetria (`DISABLE_NEW_VERSION=true`, `MODELSCOPE_LOG_LEVEL=40`, `HF_HUB_DISABLE_TELEMETRY=1`).
- `requirements.txt` — `pyannote.audio` → `modelscope`.
- `.env.example` — atualizado.
- `CLAUDE.md` — atualizado para refletir 3D-Speaker.
- `.gitignore` — adicionado `models/` (cache de modelos).
- `scripts/download_diarizer_model.py` — script de setup one-time.

#### Modelos baixados (✅ download OK)
Localização: `F:\claude-projetos\audio-agent\models\modelscope\`

| Modelo | Tamanho | Função |
|---|---|---|
| `iic/speech_campplus_speaker-diarization_common` | ~64 MB | meta-config + ONNX (multimodal) |
| `damo/speech_campplus_sv_zh-cn_16k-common` | ~28 MB | speaker embedding (CAM++) |
| `damo/speech_campplus-transformer_scl_zh-cn_16k-common` | ~15 MB | speaker change locator |
| `damo/speech_fsmn_vad_zh-cn-16k-common-pytorch` | ~3 MB | VAD (FSMN) |

#### Bug encontrado (🛑 bloqueador)

```
Segmentation fault (exit code 139)
ao executar: pipeline(task=Tasks.speaker_diarization, model=local_path)
```

Mesmo padrão do NeMo: lib Python carrega, modelos baixam, mas a inicialização do pipeline morre nativamente no Windows. Provável causa: ONNX Runtime ou extensão C++ do modelscope com incompatibilidade no Python 3.12 do Windows.

## Estado atual do código

```
diarizer.py → 3D-Speaker (modelscope)  ← código pronto, NÃO testado a inferência
worker.py    → continua chamando diarize()  ← compatível
requirements → modelscope (instalado)
modelos      → baixados em models/modelscope/  (~110 MB total)
```

A aplicação **carrega normalmente sem diarização** (`from apps.api.main import app` testado e OK). Diarização só é acionada se o job tiver `diarize=True`. Se for chamada agora, vai segfaultar.

## Próximos passos sugeridos

Em ordem de menor → maior esforço:

1. **Testar funasr direto** — `pip install funasr` e usar `AutoModel(model="fsmn-vad")` + speaker embedding por código próprio. Bypass do `modelscope.pipelines`.
2. **Tentar 3D-Speaker do GitHub direto** — clone do repo `modelscope/3D-Speaker`, usar scripts em `egs/3dspeaker/sd-pyannote/` que são PyTorch puro sem o wrapper de pipelines.
3. **simple-diarizer** — wrapper SpeechBrain. `pip install simple-diarizer`, API minimalista.
4. **Voltar para pyannote** — engolir a dependência do HF token e o ecossistema. Era o que funcionava.
5. **Cloud (AssemblyAI/Deepgram)** — desistir de local.

## Lições

1. **Sempre validar prova de conceito ANTES de migrar código.** Tanto NeMo quanto 3D-Speaker (via modelscope) tem problema nativo no Windows que só aparece em runtime. O ciclo correto é: `python -c "from x import pipeline; pipeline(...)(audio.wav)"` ANTES de mexer no app.
2. **Windows + libs de áudio chinesas/asiáticas tem fragilidade conhecida.** ModelScope, NeMo, FunASR — todos otimizados para Linux+CUDA-server.
3. **Manter a stack original como fallback** até a nova ser validada end-to-end.

## Arquivos relevantes desta sessão

- `nemo-windows-issues.md` — registro do incidente NeMo
- `diarization-status.md` — este arquivo
- `core/services/diarizer.py` — código 3D-Speaker (não testado em inferência)
- `scripts/download_diarizer_model.py` — script de download (funcional)
- `models/modelscope/` — modelos baixados
