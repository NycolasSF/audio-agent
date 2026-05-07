# NVIDIA NeMo no Windows: Erros e bloqueios encontrados

Data do registro: 2026-04-30

## Contexto

Objetivo: migrar a identificação de falantes do `audio-agent` de `pyannote` para `NVIDIA NeMo`, mantendo execução local.

O código da integração foi adaptado para `NeMo`, mas a execução no ambiente atual Windows falhou em runtime nativo.

## Erro principal observado

Ao importar `nemo.collections.asr`, o processo `python.exe` encerra com erro nativo do Windows:

```text
python.exe - Erro de Aplicativo

A instrução no 0x00007FF813AE221B referenciou a memória no 0xFFFFFFFFFFFFFFFF.
A memória não pode ser read.
```

Esse erro não sobe como exceção Python normal. O processo termina com código de saída `1`.

## Evidências coletadas

Antes do crash, a importação do `NeMo` emite apenas avisos como:

```text
WARNING:root:We couldn't create lhotse utilities directory: C:\Users\nycol\.lhotse\tools
[NeMo W ...] Megatron num_microbatches_calculator not found, using Apex version.
WARNING:nv_one_logger...
```

Depois disso, o processo morre sem traceback Python útil.

## Diagnóstico

O problema não parece ser bug do código do `audio-agent`.

A documentação oficial do `NeMo` indica que:

- `windows - amd64/x64_64` = `No support yet`
- `windows - arm64` = `No support yet`

Fontes verificadas em 2026-04-30:

- https://github.com/NVIDIA/NeMo
- https://github.com/NVIDIA-NeMo/NeMo

Conclusão prática: `NeMo` não é uma base confiável para diarização local neste projeto enquanto o runtime principal continuar em Windows.

## Instalação realizada

Comando executado:

```powershell
python -m pip install "nemo_toolkit[asr]"
```

A instalação concluiu, mas com efeitos colaterais importantes:

- `protobuf` foi trocado de `6.33.5` para `5.29.6`
- `packaging` foi trocado de `26.0` para `24.2`
- `fsspec` foi trocado de `2026.2.0` para `2024.12.0`
- `lightning` foi trocado de `2.6.1` para `2.4.0`
- `decorator` foi trocado de `4.4.2` para `5.2.1`

## Conflitos de dependência reportados pelo pip

O `pip` reportou:

```text
moviepy 1.0.3 requires decorator<5.0,>=4.0.2, but you have decorator 5.2.1 which is incompatible.
pyannote-audio 4.0.4 requires torch>=2.8.0, but you have torch 2.6.0+cu124 which is incompatible.
pyannote-audio 4.0.4 requires torchaudio>=2.8.0, but you have torchaudio 2.6.0+cu124 which is incompatible.
```

## Impacto no projeto

Estado atual:

- a integração de código para `NeMo` foi escrita;
- o import do módulo local `core.services.diarizer` funciona;
- a importação real de `nemo.collections.asr` causa crash nativo no Windows;
- portanto, a diarização com `NeMo` não está operacional neste ambiente;
- além disso, a instalação do `NeMo` alterou dependências globais do Python e pode ter criado regressões em outros componentes.

## Recomendação

Não insistir em `NeMo` rodando diretamente no Windows neste projeto.

Opções mais seguras:

1. Rodar a diarização em Linux/WSL2/container e manter o restante do `audio-agent` no Windows.
2. Abandonar `NeMo` neste ambiente e implementar uma alternativa local compatível com Windows, como pipeline com `Resemblyzer`.

## Observação sobre o código

Os arquivos do projeto foram alterados para apontar para `NeMo`, mas essa mudança deve ser reavaliada antes de colocar em produção no Windows.

Se a decisão for seguir sem WSL/Linux, o caminho recomendado é substituir a integração atual por outra stack local compatível com Windows.
