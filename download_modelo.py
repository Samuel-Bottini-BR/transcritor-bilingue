# -*- coding: utf-8 -*-
"""Download do modelo na primeira execucao, para uma pasta local, com barra de
progresso e retomada automatica. NAO empacotamos os pesos (o large-v3 passa de
3 GB); eles vem por aqui na primeira vez que o usuario escolhe o modelo."""

import os
import threading
from typing import Callable, Optional

from huggingface_hub import snapshot_download
from huggingface_hub.utils import LocalEntryNotFoundError

# Nome amigavel -> repositorio no Hugging Face + tamanho aproximado (bytes)
#
# Transcricao (Whisper) e traducao (NLLB) usam o MESMO mecanismo de download:
# mesma pasta, mesmo progresso, mesma retomada, mesma checagem offline. Os dois
# rodam em ctranslate2, entao nao ha torch nem transformers no projeto.
REPOS = {
    # transcricao
    "large-v3": ("Systran/faster-whisper-large-v3", 3_090_000_000),
    "medium":   ("Systran/faster-whisper-medium",   1_530_000_000),
    "small":    ("Systran/faster-whisper-small",       484_000_000),
    # traducao. As versoes int8 sao ~4x menores que as float32 com perda
    # pequena; num app que ja pesa 963 MB isso importa mais que o ultimo ponto
    # de qualidade.
    "nllb-600m": ("JustFrederik/nllb-200-distilled-600M-ct2-int8",   647_000_000),
    "nllb-1.3b": ("JustFrederik/nllb-200-distilled-1.3B-ct2-int8", 1_407_000_000),
}

# so os arquivos do modelo, nada de READMEs pesados
_PADROES = ["*.bin", "*.json", "*.txt", "tokenizer.json", "vocabulary.*",
            "config.json", "preprocessor_config.json", "*.model"]


class CanceladoError(Exception):
    pass


def tamanho_estimado(nome: str) -> int:
    return REPOS.get(nome, ("", 0))[1]


def modelo_ja_baixado(nome: str, base: str) -> bool:
    """True se o modelo ja esta no cache local (sem tocar na rede)."""
    if nome not in REPOS:
        return False
    repo, _ = REPOS[nome]
    try:
        snapshot_download(repo_id=repo, cache_dir=base,
                          allow_patterns=_PADROES, local_files_only=True)
        return True
    except Exception:
        return False


class _DevNull:
    def write(self, *a):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False

    def close(self):
        pass


def _fabrica_tqdm(progress: Callable[[int, int], None],
                  cancel: Optional[threading.Event]):
    """Cria uma subclasse de tqdm que soma o progresso de todos os arquivos e
    o repassa via callback progress(baixados, total).

    Subclassar o tqdm de verdade (em vez de reimplementar a interface) garante
    que todos os metodos que o huggingface_hub chama existam.
    """
    from tqdm import tqdm as _base

    lock = threading.Lock()
    barras = {}       # id -> [atual, total]
    seq = {"i": 0}

    def _reporta():
        if not barras:
            return
        # o snapshot_download cria uma barra "geral" (total = soma de todos os
        # arquivos) alem de uma por arquivo. Reportamos a de maior total, que e
        # a geral: assim o contador nao soma em dobro.
        bid = max(barras, key=lambda k: barras[k][1])
        atual, total = barras[bid]
        progress(int(atual), int(total))

    class _Tqdm(_base):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("file", _DevNull())  # nao escreve no console
            kwargs["disable"] = False
            super().__init__(*args, **kwargs)
            with lock:
                self._bid = seq["i"]
                seq["i"] += 1
                barras[self._bid] = [0, self.total or 0]

        def update(self, n=1):
            super().update(n)
            with lock:
                barras[self._bid][0] = self.n
                barras[self._bid][1] = self.total or 0
                _reporta()
            if cancel is not None and cancel.is_set():
                raise CanceladoError()

    return _Tqdm


def baixar_modelo(nome: str, base: str,
                  progress: Callable[[int, int], None] = lambda a, t: None,
                  cancel: Optional[threading.Event] = None) -> str:
    """Baixa (ou retoma) o modelo e devolve o caminho da pasta local.

    Levanta ConnectionError com mensagem clara se nao houver internet e o
    modelo ainda nao estiver baixado.
    """
    if nome not in REPOS:
        raise ValueError(f"modelo desconhecido: {nome}")

    repo, _ = REPOS[nome]
    os.makedirs(base, exist_ok=True)
    # usa o download HTTP classico (com retomada), evitando o backend "xet"
    # cujo relatorio de progresso e mais complicado de interceptar.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    # ja em cache? devolve o caminho sem tocar na rede.
    try:
        return snapshot_download(repo_id=repo, cache_dir=base,
                                 allow_patterns=_PADROES,
                                 local_files_only=True)
    except Exception:
        pass

    # baixa para o cache local (cache_dir evita a copia dupla do local_dir, o
    # que mantem o contador de MB correto). A retomada e automatica.
    try:
        return snapshot_download(
            repo_id=repo,
            cache_dir=base,
            allow_patterns=_PADROES,
            tqdm_class=_fabrica_tqdm(progress, cancel),
        )
    except CanceladoError:
        raise
    except (LocalEntryNotFoundError, OSError) as e:
        # tipicamente: sem internet na primeira vez
        raise ConnectionError(
            "Nao foi possivel baixar o modelo. Verifique a conexao com a "
            "internet: o modelo precisa ser baixado uma vez, na primeira "
            "execucao. Depois disso funciona sem internet."
        ) from e


if __name__ == "__main__":
    import sys
    nome = sys.argv[1] if len(sys.argv) > 1 else "small"

    def mostra(a, t):
        pct = (a / t * 100) if t else 0
        print(f"\r{a/1e6:7.1f} / {t/1e6:7.1f} MB  ({pct:4.1f}%)", end="")

    p = baixar_modelo(nome, "modelos", mostra)
    print(f"\n-> {p}")
