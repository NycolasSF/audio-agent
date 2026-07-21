# -*- coding: utf-8 -*-
"""Smoke test do POST /local/dictate.

Uso: python test_dictate.py <arquivo.wav>
Sem argumento, usa o WAV mais recente de ../recordings/.
Falha (exit 1) se o endpoint não devolver texto.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flow import load_vocab, post_dictate  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        rec = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "recordings")
        wavs = sorted(glob.glob(os.path.join(rec, "*.wav")), key=os.path.getmtime)
        assert wavs, "Nenhum WAV em recordings/ — passe um arquivo por argumento"
        path = wavs[-1]

    with open(path, "rb") as f:
        result = post_dictate(f.read(), load_vocab())

    print(f"arquivo : {path}")
    print(f"idioma  : {result.get('language')}  dur: {result.get('duration'):.1f}s")
    print(f"texto   : {result.get('text')!r}")
    assert result.get("text"), "Endpoint respondeu sem texto"
    print("OK")


if __name__ == "__main__":
    main()
