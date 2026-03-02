# AudioAgent

Aplicação web para **gravação de áudio do sistema** e **transcrição automática** com [OpenAI Whisper](https://github.com/openai/whisper), rodando 100% local — sem nenhuma API de terceiros.

![Interface do AudioAgent](https://github.com/NycolasSF/audio-agent/raw/main/static/preview.png)

---

## Funcionalidades

- Captura o áudio do sistema (loopback WASAPI) — sem necessidade de Stereo Mix
- Transcrição local com Whisper (tiny → large), selecionável na interface
- Aceleração por GPU (CUDA) detectada automaticamente
- Progresso da transcrição em tempo real (%)
- Histórico de transcrições com persistência entre recarregamentos
- Títulos editáveis gerados automaticamente a partir do texto
- Exportação por card: `.txt`, `.md` (com timestamps), `.vtt`, `.pdf`
- Exclusão individual de transcrições
- **Timer preciso** — baseado em `Date.now()`, continua correto mesmo com a aba em background
- **WebSocket com heartbeat** — ping/pong a cada 25s para manter conexão estável em gravações longas
- **Detecção de queda** — notifica automaticamente se a gravação for interrompida de forma inesperada
- **Sons** (Web Audio API) — bipe ao iniciar/parar, ding ao concluir transcrição, alerta em erros
- **Notificações do sistema** — alertas nativos do OS para transcrição concluída e erros, mesmo com a aba minimizada

---

## Requisitos

| Item | Versão mínima |
|------|--------------|
| Windows | 10 / 11 |
| Python | 3.10+ |
| GPU NVIDIA + CUDA | Opcional (cai para CPU) |

> **Nota:** A captura via WASAPI loopback funciona apenas no Windows.

---

## Instalação

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

> Se você tiver GPU NVIDIA, instale o PyTorch com suporte a CUDA seguindo as
> instruções em [pytorch.org](https://pytorch.org/get-started/locally/) antes
> de rodar `pip install -r requirements.txt`.

---

## Como usar

```bash
# Windows: execute start.bat   OU
python main.py
```

Acesse **http://localhost:8000** no navegador.

| Ação | Como fazer |
|------|-----------|
| Gravar | Clique no botão central |
| Parar e transcrever | Clique novamente |
| Trocar modelo Whisper | Seletor no cabeçalho |
| Editar título do card | Clique no campo de título |
| Exportar transcrição | Botão **↓ Exportar** em cada card |
| Excluir transcrição | Botão **✕** no canto do card |

A transcrição roda em segundo plano — você pode iniciar uma nova gravação enquanto a anterior é processada.

---

## Estrutura do projeto

```
audio-agent/
├── main.py           # Servidor FastAPI (WebSocket + endpoints REST)
├── recorder.py       # Captura de áudio via WASAPI loopback
├── transcriber.py    # Transcrição com Whisper + progresso em tempo real
├── static/
│   └── index.html    # Interface web (sem dependências externas)
├── requirements.txt
├── install.bat       # Instalação das dependências (Windows)
├── start.bat         # Atalho para iniciar o servidor (Windows)
└── .env.example      # Variáveis de ambiente opcionais
```

### Dados gerados (ignorados pelo git)

| Caminho | Conteúdo |
|---------|----------|
| `recordings/` | Arquivos `.wav` temporários das gravações |
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

Crie um arquivo `.env` na raiz do projeto (opcional):

```env
# Modelo padrão ao iniciar (pode ser alterado na interface sem reiniciar)
WHISPER_MODEL=base
```

---

## Licença

MIT
