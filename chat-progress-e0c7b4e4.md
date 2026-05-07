# Progresso da Sessão — Caminho 1 (WSL2 + 3D-Speaker)

**Chat ID:** `e0c7b4e4-4e30-40bf-ab1e-47d84aa72fe8`
**Data:** 2026-04-30
**Status:** ⏸️ Pausado — aguardando ativação de virtualização no BIOS

---

## Onde paramos

Fomos pelo **Caminho 1 — arquitetura híbrida (Windows + microserviço WSL2 com 3D-Speaker)**.

O setup parou no bloqueio:

```
Virtualização Habilitada no Firmware: Não
Código de erro: Wsl/InstallDistro/Service/RegisterDistro/CreateVm/HCS/HCS_E_HYPERV_NOT_INSTALLED
```

A placa-mãe está com **VT-x/AMD-V desligado no BIOS/UEFI**. Sem isso o WSL2 não roda.

---

## ✅ Já feito (não precisa refazer)

### 1. Reversão da migração NeMo
- Arquivos NeMo revertidos via `git checkout HEAD --` (no commit, foi só working tree).
- `nemo_toolkit` desinstalado.
- Deps rebaixadas restauradas: `protobuf 7.34.1`, `packaging 26.2`, `fsspec 2026.4.0`, `lightning 2.6.1`, `decorator 4.4.2`.
- App principal valida com `from apps.api.main import app` (smoke OK).
- Documentado em `nemo-windows-issues.md` na raiz.

### 2. Reset de senha do usuário
- `nycolas@gmail.com` em `transcriptions/data.db`
- Senha temporária: **`audioagent2026`** (bcrypt aplicado)
- Trocar pela UI no próximo login

### 3. Tentativa 3D-Speaker via modelscope.pipelines
- Falhou no Windows com **segfault** (mesmo padrão Windows do NeMo).
- Modelos baixados ficaram em `models/modelscope/` (~110 MB total) — **úteis pro caminho WSL2**, **não apagar**.
- Documentado em `diarization-status.md` na raiz.

### 4. Decisão arquitetural
- Caminho 1 escolhido: hybrid Windows + WSL2.
- Engine: **3D-Speaker via ModelScope no Linux** (NÃO NeMo — 3D-Speaker já tem modelos baixados e código pronto).

### 5. WSL2 base
- Kernel WSL2 instalado, padrão = 2.
- Componente "Plataforma da Máquina Virtual" do Windows: **ativado** via `wsl --install --no-distribution` (concluído com êxito).

### 6. Memórias persistentes salvas
- `feedback_validate_before_migrating.md` — sempre rodar PoC antes de migrar
- `project_diarization_state.md` — estado da diarização

---

## ⏳ Pendente — quando você voltar do BIOS

### Passo 0 (você faz manualmente antes desta sessão recomeçar)
1. Reboot
2. Entrar no BIOS/UEFI (tecla varia por placa: F2, F10, F12, Del, F1)
3. Habilitar **"Intel Virtualization Technology" / "VT-x"** ou **"SVM Mode" / "AMD-V"**
4. Salvar (F10) e sair
5. Confirmar pelo PowerShell:
   ```powershell
   systeminfo | Select-String "Virtualização Habilitada no Firmware"
   ```
   Tem que retornar `Sim`.

### Passo 1 — Instalar Ubuntu 22.04 no WSL2
```powershell
wsl --install -d Ubuntu-22.04 --no-launch
wsl --set-default Ubuntu-22.04
wsl --list --verbose   # confirmar: Ubuntu-22.04   Stopped   2
```

### Passo 2 — Setup Python no Ubuntu (rodar como root)
```bash
wsl -d Ubuntu-22.04 -u root -- bash -c "
apt update -y &&
apt install -y python3 python3-pip python3-venv ffmpeg libsndfile1 &&
mkdir -p /opt/audio-diarizer &&
python3 -m venv /opt/audio-diarizer/venv &&
/opt/audio-diarizer/venv/bin/pip install --upgrade pip &&
/opt/audio-diarizer/venv/bin/pip install modelscope addict simplejson sortedcontainers fastapi uvicorn 'numpy<2' torch torchaudio --index-url https://download.pytorch.org/whl/cpu
"
```
*Nota: `cpu` só pra começar. CUDA no WSL2 dá pra adicionar depois.*

### Passo 3 — Smoke test no WSL2 (CRUCIAL — antes de mexer em qualquer código!)
```bash
wsl -d Ubuntu-22.04 -u root -- /opt/audio-diarizer/venv/bin/python -c "
import os
os.environ['MODELSCOPE_CACHE'] = '/mnt/f/claude-projetos/audio-agent/models/modelscope'
os.environ['DISABLE_NEW_VERSION'] = 'true'
os.environ['MODELSCOPE_LOG_LEVEL'] = '40'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
p = pipeline(task=Tasks.speaker_diarization, model='/mnt/f/claude-projetos/audio-agent/models/modelscope/iic/speech_campplus_speaker-diarization_common')
r = p('/mnt/f/claude-projetos/audio-agent/models/modelscope/iic/speech_campplus_speaker-diarization_common/examples/2speakers_example.wav')
print('OK:', r)
"
```

**Se passar → continuar. Se segfaultar → fallback Sherpa-ONNX (caminho 2) ou pyannote.**

### Passo 4 — Microserviço FastAPI no WSL2
Criar `F:\claude-projetos\audio-agent\wsl-diarizer\server.py`:
```python
import os
os.environ['MODELSCOPE_CACHE'] = '/mnt/f/claude-projetos/audio-agent/models/modelscope'
os.environ['DISABLE_NEW_VERSION'] = 'true'
os.environ['MODELSCOPE_LOG_LEVEL'] = '40'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks

MODEL_PATH = '/mnt/f/claude-projetos/audio-agent/models/modelscope/iic/speech_campplus_speaker-diarization_common'
_pipe = None

def get_pipe():
    global _pipe
    if _pipe is None:
        _pipe = pipeline(task=Tasks.speaker_diarization, model=MODEL_PATH)
    return _pipe

app = FastAPI()

class DiarizeReq(BaseModel):
    file: str  # caminho /mnt/f/...
    num_speakers: int | None = None

@app.post('/diarize')
def diarize(req: DiarizeReq):
    try:
        kwargs = {'oracle_num_speakers': req.num_speakers} if req.num_speakers else {}
        raw = get_pipe()(req.file, **kwargs)
        items = raw.get('text') if isinstance(raw, dict) else raw
        out = []
        for it in items or []:
            if isinstance(it, (list, tuple)):
                start, end, spk = float(it[0]), float(it[1]), int(it[2])
            else:
                start = float(it.get('start', 0))
                end = float(it.get('end') or it.get('stop') or 0)
                spk = int(it.get('spk', it.get('speaker', 0)))
            out.append({'start': round(start, 3), 'end': round(end, 3),
                       'speaker': f'SPEAKER_{spk:02d}'})
        return {'segments': out}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get('/health')
def health():
    return {'ok': True}
```

Script de boot `wsl-diarizer/start.sh`:
```bash
#!/bin/bash
cd /mnt/f/claude-projetos/audio-agent/wsl-diarizer
exec /opt/audio-diarizer/venv/bin/uvicorn server:app --host 127.0.0.1 --port 9020
```

### Passo 5 — Reescrever `core/services/diarizer.py` no Windows pra fazer HTTP
Novo conteúdo (substitui o atual que ainda tem código modelscope local):
```python
"""Speaker diarization via WSL2 microservice (3D-Speaker no Linux)."""
from __future__ import annotations
import requests
from core import settings

DIARIZER_URL = settings.DIARIZER_URL  # default 'http://127.0.0.1:9020'

def diarize(file_path: str, num_speakers: int | None = None) -> list:
    # converte path Windows → /mnt/f/...
    p = file_path.replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        p = f'/mnt/{p[0].lower()}{p[2:]}'
    r = requests.post(
        f'{DIARIZER_URL}/diarize',
        json={'file': p, 'num_speakers': num_speakers},
        timeout=600,
    )
    r.raise_for_status()
    return r.json()['segments']

def merge_speaker_labels(whisper_segs: list, diarize_segs: list) -> list:
    out = []
    for seg in whisper_segs:
        best, best_ov = "UNKNOWN", 0.0
        for d in diarize_segs:
            ov = min(seg["end"], d["end"]) - max(seg["start"], d["start"])
            if ov > best_ov:
                best_ov, best = ov, d["speaker"]
        out.append({**seg, "speaker": best})
    return out
```

Adicionar em `core/settings.py`:
```python
DIARIZER_URL: str = os.getenv("DIARIZER_URL", "http://127.0.0.1:9020")
```

### Passo 6 — Atualizar `.env.example`, remover referências a modelscope/HF locais
Substituir bloco de diarização por:
```env
# Diarização via microserviço WSL2 (caminho 1 da arquitetura híbrida)
DIARIZER_URL=http://127.0.0.1:9020
```

### Passo 7 — Atualizar `requirements.txt`
- Remover: `modelscope`
- Adicionar: nada (requests já vem como dep transitiva)

### Passo 8 — Smoke test end-to-end
1. Iniciar microserviço:
   ```powershell
   wsl -d Ubuntu-22.04 -u root -- /mnt/f/claude-projetos/audio-agent/wsl-diarizer/start.sh
   ```
2. Em outro terminal, iniciar app:
   ```powershell
   python main.py
   ```
3. Upload de áudio com diarização ligada → ver se chega segmentos com `speaker`.

### Passo 9 — Documentar no CLAUDE.md a nova arquitetura híbrida.

---

## 📂 Arquivos importantes desta sessão

| Arquivo | Status | Propósito |
|---|---|---|
| `nemo-windows-issues.md` | ✅ existe | Registro do incidente NeMo |
| `diarization-status.md` | ✅ existe | Estado da migração 3D-Speaker (Windows) |
| `chat-progress-e0c7b4e4.md` | ✅ este arquivo | Retomar daqui após BIOS |
| `models/modelscope/` | ✅ ~110 MB baixado | **NÃO APAGAR** — usar do WSL2 via /mnt/f/ |
| `core/services/diarizer.py` | ⚠️ código modelscope local | Será substituído no Passo 5 |
| `core/settings.py` | ⚠️ tem `DIARIZATION_*` | Adicionar `DIARIZER_URL` no Passo 5 |
| `requirements.txt` | ⚠️ tem `modelscope` | Remover no Passo 7 |
| `.env.example` | ⚠️ tem `DIARIZATION_*` | Substituir no Passo 6 |
| `scripts/download_diarizer_model.py` | ⚠️ tem warm-up que segfauta | Pode apagar ou manter (só baixa modelos) |
| `scripts/smoke_test_diarizer.py` | ⚠️ testa modelscope local | Apagar após validação WSL2 |

---

## 🔄 Como retomar esta sessão

Quando voltar do BIOS, abra novo chat e cole:

```
Estou retomando a sessão e0c7b4e4. Leia o arquivo
F:\claude-projetos\audio-agent\chat-progress-e0c7b4e4.md
e continue do "Passo 1 — Instalar Ubuntu 22.04".
```

Eu pego do exato ponto onde paramos.

---

## ⚠️ Lições críticas (já gravadas em memória persistente)

1. **Validar PoC isolado ANTES de migrar código.** NeMo e 3D-Speaker quebraram pelo mesmo motivo (segfault só em runtime real). Ambos os incidentes salvos em memória.
2. **Manter pyannote como fallback** até nova engine validar end-to-end.
3. **Modelos baixados do ModelScope são reutilizáveis no WSL2** — `/mnt/f/.../models/modelscope/` é o mesmo arquivo, sem cópia.
