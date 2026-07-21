# 🎙️ transcritor — tool de transcrição do hub (guia de uso)

Servidor local de transcrição de fala → texto (Whisper na GPU, com timestamps por palavra). É a **única via de transcrição** do `claude-projetos`: qualquer script que precise transformar áudio/vídeo em texto chama ESTE servidor, nunca um Whisper próprio.

> Este doc é sobre **como usar** a tool. Para configurar/ajustar o servidor (env, diarização, engine, troubleshooting de boot), veja o `CLAUDE.md` desta pasta.

---

## ⛔ Regra de ouro

**NUNCA carregar Whisper local** em um script (`whisper.load_model(...)` do openai-whisper, ou `faster_whisper.WhisperModel(...)`). A GPU é única (RTX 3060 Ti, 8 GB); dois modelos carregados ao mesmo tempo — um script local competindo com o servidor, ou dois scripts locais em terminais diferentes — estouram a VRAM e dão `CUDA out of memory`. O servidor serializa os jobs numa fila e é o **único dono da GPU**.

> Incidente que originou a regra (jun/2026): vários pipelines de lançamento rodando `whisper.load_model("large-v3")` local derrubaram a transcrição com OOM em cascata.

Antes de aprovar/escrever um script de transcrição, confira: `grep -rn "load_model(\|WhisperModel(" <pasta>` deve dar vazio (fora o próprio servidor).

---

## Ligar o servidor

- Rodar `F:\claude-projetos\_infra\transcritor\start.bat` (ou `python main.py` na pasta). Sobe em `http://localhost:8020`.
- Se já estiver no ar, o `start.bat` apenas abre o painel de acompanhamento (não sobe um segundo).
- O cliente (abaixo) já espera o servidor subir sozinho (`wait_server`), então em geral você nem precisa ligar na mão — mas se a GPU estiver ocupada por outra coisa, ligue antes.

---

## Cliente canônico

Um módulo stdlib puro (urllib, sem dependências) que fala com a API. Importe por caminho absoluto:

```python
import sys
sys.path.insert(0, r"F:\claude-projetos\_infra\transcritor\clients")
from transcritor_client import transcribe_file, transcribe_media, transcribe_span
```

Três funções de entrada:

| Função | Quando usar |
|---|---|
| `transcribe_file(path, ...)` | áudio já em formato aceito: `.mp3 .mp4 .wav .m4a .ogg .webm .flac` |
| `transcribe_media(path, ...)` | **qualquer** mídia; se a extensão não for aceita (ex.: `.mov`), extrai um WAV 16 kHz mono via ffmpeg antes de subir |
| `transcribe_span(path, start, end, ...)` | retranscreve SÓ o trecho `[start, end]` (segundos) — para reparar um intervalo ruim de uma transcrição prévia com modelo maior; timestamps voltam rebaseados para o arquivo original |

Na dúvida, use `transcribe_media` — ele cobre os dois casos comuns. O fluxo de revisão (medium primeiro, reparo por span) é orquestrado pela sonda `audiosmith` (`AGENTS/audiosmith/prompt.md`).

### Parâmetros

```python
transcribe_media(
    path,                 # caminho do arquivo
    model="large-v3",     # tiny | base | small | medium | large-v3
    language="pt",        # código ISO; None = autodetecta
    diarize=False,        # True = separa locutores (microsserviço WSL precisa estar no ar)
    token=None,           # reaproveite o token em lote (evita re-login a cada arquivo)
    timeout=1800,         # segundos de espera pelo job
    progress_cb=None,     # callback(pct) chamado a cada avanço de %
)
```

### O que retorna — o `job`

```python
{
  "id": "a8afd5e1",
  "text": "Seja muito bem-vindo ...",         # texto completo
  "language": "pt",
  "segments": [
    {
      "start": 0.0, "end": 4.2, "text": "Seja muito bem-vindo ...",
      "words": [ {"word": " Seja", "start": 0.0, "end": 0.48, "probability": 0.63}, ... ]
    },
    ...
  ]
}
```

---

## Receitas

**Transcrição simples (só o texto):**
```python
job = transcribe_media(r"C:\aula.mp3", model="medium", language="pt")
print(job["text"])
```

**Word-level (para legendas / @remotion/captions):**
```python
job = transcribe_media(r"C:\take.mov", model="large-v3", language="pt")
words = [w for seg in job["segments"] for w in seg.get("words", [])]
# cada w: {"word","start","end","probability"}
```

**Com barra de progresso:**
```python
job = transcribe_media(path, model="large-v3", progress_cb=lambda p: print(f"{p}%"))
```

**Lote (reaproveitando o token e o servidor):**
```python
from transcritor_client import wait_server
token = wait_server()                      # espera subir e loga uma vez
for arquivo in lista:
    job = transcribe_media(arquivo, model="large-v3", language="pt", token=token)
    salvar(arquivo, job["text"])
```
> Mande os arquivos **um a um** (sequencial). O servidor já usa a GPU de forma ótima por job; disparar vários em paralelo só faz eles competirem.

---

## Modelos

| Modelo | Uso | Nota |
|---|---|---|
| `tiny` / `base` | rascunho rápido, áudio limpo | qualidade menor |
| `small` | meio-termo | |
| `medium` | bom PT-BR, rápido | ótimo custo/benefício |
| `large-v3` | máxima qualidade | **cabe na GPU de 8 GB** (o servidor mantém 1 modelo por vez na placa) |

Se um dia faltar VRAM (ex.: rodar diarização junto do `large-v3`), suba o servidor com `WHISPER_COMPUTE_TYPE=int8_float16` no `.env` — menos VRAM, perda de qualidade desprezível.

---

## Troubleshooting de uso

- **`RuntimeError: transcritor fora do ar`** → o servidor não subiu; rode o `start.bat`.
- **Travou em `stuck`** → o cliente já tolera `stuck` transitório (race ao iniciar o job); só falha se persistir >60 s, o que indica que o servidor caiu de verdade — religue.
- **`CUDA out of memory`** → o servidor agora **se auto-recupera** (libera a VRAM no erro) e mantém só 1 modelo na GPU; não precisa reiniciar na mão. Se persistir, é sinal de outro processo segurando a GPU — feche-o (`nvidia-smi` mostra quem).

---

## Referências

- Cliente: `clients/transcritor_client.py`
- Exemplo real de pipeline em lote (word-level, retry por take): `CLIENTES/marcio-medeiros-educacao/LANCAMENTOS/jul26-imersao-contabilidade/1-CAPTACAO/criativos/Videos/Para edicao/leva 1/_PIPELINE/_scripts/transcrever_audio_agent.py`
- Config/ajuste do servidor: `CLAUDE.md` (esta pasta)
