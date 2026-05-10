# AudioAgent

Aplicação web para **gravação, upload e transcrição automática de áudio** com [OpenAI Whisper](https://github.com/openai/whisper), rodando 100% local — sem nenhuma API de terceiros.

---

## Funcionalidades

### Gravação
- **Modo Microfone** — captura o microfone padrão do sistema
- **Modo Sistema (WASAPI)** — captura o áudio do sistema (loopback), sem necessidade de Stereo Mix
- **Modo Abas** — grava o áudio de uma ou mais abas/janelas do navegador simultaneamente, sem sobreposição de saída de som; o nome da gravação é extraído automaticamente do título da página

### Upload
- Upload de arquivos de áudio/vídeo (`.mp3`, `.mp4`, `.wav`, `.m4a`, `.ogg`, `.webm`, `.flac`)
- Nome do arquivo usado como título padrão da transcrição

### Transcrição
- Whisper local (tiny → large), selecionável na interface
- Aceleração por GPU (CUDA) detectada automaticamente
- **Progresso em % em tempo real** durante toda a transcrição (gravação ou upload)
- Re-transcrição com modelo diferente diretamente pelo painel de detalhe
- Recuperação automática de itens travados após reinício do servidor

### Histórico
- Painel de detalhe ao clicar em qualquer linha: texto com marcações de tempo clicáveis, metadados, sidebar de exportação
- Títulos editáveis (ícone de lápis ao hover ou campo no painel de detalhe)
- Exportação: `.txt`, `.md`, `.vtt`, `.pdf`
- Exclusão individual

### UX
- Checkboxes com estilo neon para seleção em massa
- Timer preciso baseado em `Date.now()` (continua correto com aba em background)
- WebSocket com heartbeat (ping/pong a cada 25s) para gravações longas
- Sons de feedback (Web Audio API) e notificações nativas do OS

---

## Requisitos

| Item | Versão mínima |
|------|--------------|
| Windows | 10 / 11 |
| macOS | 12 Monterey (Apple Silicon ou Intel) |
| Python | 3.10+ |
| GPU NVIDIA + CUDA | Opcional no Windows (cai para CPU) |
| Apple Silicon MPS | Opcional no macOS (cai para CPU) |

> **Notas de plataforma:**
> - **Captura do sistema (loopback)**: nativa no Windows via WASAPI. No macOS exige driver de áudio virtual (BlackHole, Loopback ou similar).
> - **Diarização (3D-Speaker)**: roda em WSL2 no Windows e nativa no macOS (sem WSL).
> - **Modo Abas**: requer Chrome/Edge 109+ (funciona em ambos os sistemas).

---

## Instalação (Windows)

```bash
# 1. Clone o repositório
git clone https://github.com/NycolasSF/audio-agent.git
cd audio-agent

# 2. Instale as dependências
#    Windows: execute install.bat   OU
pip install -r requirements.txt

# 3. (Opcional) Copie e ajuste o arquivo de ambiente
copy .env.example .env
```

> Se você tiver GPU NVIDIA, instale o PyTorch com suporte a CUDA em [pytorch.org](https://pytorch.org/get-started/locally/) antes de rodar `pip install`.

---

## Instalação (macOS)

No macOS não é preciso usar WSL — a diarização (3D-Speaker) roda nativa. A única peça que muda é a captura de áudio do sistema, que exige um driver virtual (BlackHole).

### 1. Pré-requisitos via Homebrew

```bash
# Instale o Homebrew se ainda não tiver: https://brew.sh
brew install python@3.12 ffmpeg git

# (Opcional) BlackHole 2ch para capturar o áudio do sistema (modo Loopback)
brew install --cask blackhole-2ch
```

> O `pyaudiowpatch` (usado no Windows para WASAPI loopback) **não instala no macOS**. No Mac, a captura do sistema é feita roteando o áudio para o BlackHole e selecionando-o como dispositivo de entrada — ou usando o modo **Abas** do navegador, que funciona sem driver extra.

### 2. Clone e venv

```bash
git clone https://github.com/NycolasSF/audio-agent.git
cd audio-agent

python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. PyTorch

```bash
# Apple Silicon (M1/M2/M3/M4) — usa MPS (GPU integrada da Apple)
pip install torch torchaudio

# Intel Mac — apenas CPU
pip install torch torchaudio
```

### 4. Demais dependências

```bash
pip install -r requirements.txt
```

> Se algum pacote Windows-only (ex.: `pyaudiowpatch`) estiver listado em `requirements.txt` e falhar, instale o restante ignorando-o:
> ```bash
> grep -v pyaudiowpatch requirements.txt | pip install -r /dev/stdin
> ```

### 5. Diarização nativa (opcional)

A diarização usa 3D-Speaker via ModelScope. No macOS roda nativa, sem microsserviço WSL:

```bash
pip install 'numpy<2' modelscope datasets funasr soundfile \
  addict simplejson sortedcontainers pillow opencv-python-headless \
  hdbscan umap-learn pyyaml kaldiio librosa scipy
```

Configure o `.env` para apontar o diarizer pra `localhost` (sem WSL):

```bash
cp .env.example .env
# edite e ajuste:
#   DIARIZER_AUTOSTART=false
#   DIARIZER_URL=http://127.0.0.1:9020
```

Rode o microsserviço de diarização em outro terminal **somente quando precisar**:

```bash
cd wsl-diarizer
uvicorn server:app --host 127.0.0.1 --port 9020
```

> Se você não vai usar diarização (`diarize=False` em todos os jobs), pode pular este passo inteiro.

### 6. Capturar áudio do sistema com BlackHole (opcional)

1. Abra **Configurações de MIDI/Áudio** (`Audio MIDI Setup`).
2. Crie um **Multi-Output Device** com `BlackHole 2ch` + sua saída normal (alto-falante/fone). Isso permite ouvir e gravar ao mesmo tempo.
3. Defina o Multi-Output Device como saída padrão do sistema.
4. No AudioAgent, escolha `BlackHole 2ch` como dispositivo de entrada.

---

## Como usar

```bash
# Windows: execute start.bat   OU
python main.py

# macOS (com venv ativo):
source .venv/bin/activate
python main.py
```

Acesse **http://localhost:8020** no navegador.

| Ação | Como fazer |
|------|-----------|
| Gravar (microfone/sistema) | Selecione o modo e clique no botão central |
| Gravar abas | Pill **Abas** → adicione fontes → **Gravar** |
| Transcrever arquivo | Pill **Arquivo** → selecione arquivo e modelo |
| Ver transcrição completa | Clique em qualquer linha da tabela |
| Re-transcrever | Painel de detalhe → escolha modelo → **↻ Re-transcrever** |
| Renomear | Ícone de lápis ao passar o mouse no título |
| Exportar | Sidebar do painel de detalhe ou menu `···` |

---

## Arquitetura do fluxo de transcrição

```
┌─────────────────────────────────────────────────────────────┐
│                         FRONTEND                            │
│                                                             │
│  [Gravação / Upload / Re-transcrever]                       │
│         │                        │                          │
│    WebSocket               POST /upload                     │
│   "stop_record"         POST /retranscribe                  │
│         │                        │                          │
└─────────┼────────────────────────┼──────────────────────────┘
          │                        │
┌─────────▼────────────────────────▼──────────────────────────┐
│                          BACKEND (main.py)                  │
│                                                             │
│  ┌─── JOB CRIADO ────────────────────────────────────────┐  │
│  │                                                       │  │
│  │  WebSocket handler         REST endpoint              │  │
│  │  ─────────────────         ─────────────────          │  │
│  │  _transcribe_background()  _transcribe_background_    │  │
│  │  (envia progresso via WS)  rest()  (via polling)      │  │
│  │                                                       │  │
│  │  loop.run_in_executor(executor, lambda: ...)          │  │
│  │           │                      │                    │  │
│  └───────────┼──────────────────────┼────────────────────┘  │
│              │                      │                        │
│  ┌─── WORKER (ThreadPoolExecutor, max_workers=2) ────────┐  │
│  │           ▼                      ▼                    │  │
│  │   transcribe_with_progress(file, model, device,       │  │
│  │                            progress_cb)               │  │
│  │              │                                        │  │
│  │     [Whisper tqdm hook]                               │  │
│  │     progress_cb(pct) a cada chunk de áudio            │  │
│  │              │                                        │  │
│  │    Via WS: ws.send_json({percent})   ─── ao frontend  │  │
│  │    Via REST: _active_progress[id]=pct ── polling 1.5s │  │
│  │                                                       │  │
│  └─── RESULTADO PERSISTIDO ─────────────────────────────┘  │
│              │                                              │
│    persist_transcription()  →  transcriptions/data.json     │
│    _active_progress.pop(id)  (cleanup)                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
          │                        │
┌─────────▼────────────────────────▼──────────────────────────┐
│                         FRONTEND                            │
│                                                             │
│  WS "transcription_complete"   GET /transcriptions/{id}/    │
│  → completeRow()               status → {status:"done"}     │
│  → store atualizado            → completeRow()              │
│  → painel de detalhe pronto    → store atualizado           │
└─────────────────────────────────────────────────────────────┘
```

### Resumo: onde o job é criado e onde o worker persiste

| Etapa | Gravação (WebSocket) | Upload / Re-transcrever (REST) |
|-------|---------------------|-------------------------------|
| **Job criado** | `websocket_endpoint` ao receber `action: stop` | `POST /upload` ou `POST /transcriptions/{id}/retranscribe` |
| **Worker lançado** | `loop.run_in_executor(executor, _transcribe_background)` | `loop.run_in_executor(executor, _transcribe_background_rest)` |
| **Progresso reportado** | `ws.send_json({type:"transcription_progress", percent})` via `run_coroutine_threadsafe` | `_active_progress[id] = pct` → lido pelo `GET /status` |
| **Resultado persistido** | `persist_transcription()` → `data.json` | `persist_transcription()` → `data.json` |
| **Cleanup** | — | `_active_progress.pop(id)` no `finally` |

---

## Estrutura do projeto

```
audio-agent/
├── main.py           # Servidor FastAPI (WebSocket + endpoints REST)
├── recorder.py       # Captura de áudio via WASAPI loopback
├── transcriber.py    # Transcrição com Whisper + hook de progresso via tqdm
├── static/
│   └── index.html    # Interface web (sem dependências externas)
├── requirements.txt
├── install.bat
├── start.bat
└── .env.example
```

### Dados gerados (ignorados pelo git)

| Caminho | Conteúdo |
|---------|---------|
| `recordings/` | Arquivos de áudio das gravações e uploads |
| `transcriptions/data.json` | Histórico de transcrições salvo localmente |

---

## Modelos Whisper

| Modelo | VRAM aprox. | Qualidade |
|--------|-------------|-----------|
| tiny   | ~1 GB | Básica |
| base   | ~1 GB | Boa (padrão) |
| small  | ~2 GB | Melhor |
| medium | ~5 GB | Ótima |
| large  | ~10 GB | Máxima |

O modelo é baixado automaticamente na primeira utilização e cacheado localmente.

---

## Variáveis de ambiente

```env
# Modelo padrão ao iniciar (alterável na interface sem reiniciar)
WHISPER_MODEL=base
```

---

## Licença

MIT
