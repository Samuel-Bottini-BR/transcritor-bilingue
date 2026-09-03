# -*- coding: utf-8 -*-
"""Registra as pastas das DLLs CUDA (cuBLAS/cuDNN) para o ctranslate2
encontra-las na GPU. No Windows, Python 3.8+ nao procura DLL no PATH; e preciso
os.add_dll_directory. Importe este modulo ANTES de faster_whisper/ctranslate2.

Funciona tanto no venv de desenvolvimento (site-packages/nvidia/*/bin) quanto
no app empacotado (as DLLs ficam ao lado do executavel, em _internal)."""

import os
import sys


def registrar_dlls_cuda():
    candidatos = []

    # 1) app empacotado pelo PyInstaller: DLLs ao lado do executavel
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidatos += [
            base,
            os.path.join(base, "_internal"),
            os.path.join(base, "_internal", "nvidia_bin"),
        ]

    # 2) venv de desenvolvimento: pacotes pip nvidia-*-cu12.
    # 'nvidia' e um namespace package (__file__ e None), entao usamos __path__.
    try:
        import nvidia  # noqa: F401
        for raiz in list(nvidia.__path__):
            for sub in os.listdir(raiz):
                b = os.path.join(raiz, sub, "bin")
                if os.path.isdir(b):
                    candidatos.append(b)
    except Exception:
        pass

    registradas = []
    for d in candidatos:
        if d and os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            # o ctranslate2 carrega cublas/cudnn em runtime via LoadLibrary com
            # nome puro, que NAO consulta as pastas de add_dll_directory. Por
            # isso tambem prependemos ao PATH, que o LoadLibrary consulta.
            if d not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            registradas.append(d)
    return registradas


# registra ao importar
DLLS_CUDA = registrar_dlls_cuda()
