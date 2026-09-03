#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Traducao das legendas com NLLB-200 rodando em ctranslate2.

Por que ctranslate2 e nao transformers: o projeto ja usa ctranslate2 para o
Whisper, com as DLLs de CUDA empacotadas. Usar o caminho padrao do NLLB
(transformers) obrigaria a instalar o torch, que sozinho quase dobraria o
tamanho do instalador. Aqui o modelo de traducao usa exatamente o mesmo
runtime, o mesmo device e a mesma pasta de modelos.

O ganho que importa num arquivo bilingue: a linha que JA esta no idioma de
destino nao e traduzida, so copiada. Num filme metade ingles / metade italiano
traduzido para ingles, isso corta perto de metade do trabalho.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Iterable, Optional

# IMPORTANTE: registra as DLLs do CUDA antes de importar ctranslate2, senao o
# cuBLAS nao e encontrado e a traducao quebra na primeira chamada. O modelo
# chega a CARREGAR na GPU sem isso - o erro so aparece na hora de calcular.
import cuda_setup  # noqa: F401

import ctranslate2
from tokenizers import Tokenizer

# Mesma assinatura de motor.py: cb(etapa, atual, total)
ProgressCb = Callable[[str, int, int], None]


class CanceladoError(Exception):
    """Levantada quando o usuario cancela no meio da traducao."""


def _noop(*_args, **_kwargs) -> None:
    pass


def _checa_cancelamento(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise CanceladoError()


# --------------------------------------------------------------------------
# Codigos de idioma
# --------------------------------------------------------------------------

# O Whisper usa ISO-639-1 de duas letras; o NLLB usa FLORES-200
# (idioma + sistema de escrita). A traducao entre os dois precisa ser
# explicita: nao da para derivar um do outro.
CODIGOS = {
    "en": "eng_Latn", "it": "ita_Latn", "pt": "por_Latn", "es": "spa_Latn",
    "fr": "fra_Latn", "de": "deu_Latn", "nl": "nld_Latn", "ca": "cat_Latn",
    "gl": "glg_Latn", "ro": "ron_Latn", "pl": "pol_Latn", "cs": "ces_Latn",
    "sv": "swe_Latn", "da": "dan_Latn", "no": "nob_Latn", "fi": "fin_Latn",
    "el": "ell_Grek", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "tr": "tur_Latn",
    "ar": "arb_Arab", "he": "heb_Hebr", "hi": "hin_Deva", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "zh": "zho_Hans", "vi": "vie_Latn", "id": "ind_Latn",
    "la": "lat_Latn",   # ver idioma_suportado(): pode nao existir no modelo
}


def codigo_nllb(iso2: str) -> Optional[str]:
    return CODIGOS.get((iso2 or "").lower())


# --------------------------------------------------------------------------
# O tradutor
# --------------------------------------------------------------------------

class Tradutor:
    """Carrega o NLLB uma vez e traduz varios lotes.

    Use como contexto (`with Tradutor(...) as t:`) para garantir que a memoria
    da GPU seja liberada: com 4 GB de VRAM, deixar este modelo carregado
    impede o Whisper de voltar para a placa.
    """

    def __init__(self, caminho_modelo: str, device: str = "auto",
                 compute_type: Optional[str] = None,
                 log: Callable[[str], None] = _noop):
        if device == "auto":
            device = "cuda" if _tem_gpu() else "cpu"
        # o modelo baixado ja e int8; no CUDA o int8_float16 e mais rapido e
        # cabe com folga, na CPU o int8 puro e o caminho normal
        if compute_type is None:
            compute_type = "int8_float16" if device == "cuda" else "int8"

        tok = os.path.join(caminho_modelo, "tokenizer.json")
        if not os.path.isfile(tok):
            raise FileNotFoundError(
                f"tokenizer.json nao encontrado em {caminho_modelo}")

        log(f"carregando tradutor em {device} ({compute_type})...")
        try:
            self.tradutor = ctranslate2.Translator(
                caminho_modelo, device=device, compute_type=compute_type)
        except Exception as e:
            if device == "cuda":
                log(f"  falhou na GPU ({e}); usando CPU")
                device, compute_type = "cpu", "int8"
                self.tradutor = ctranslate2.Translator(
                    caminho_modelo, device=device, compute_type=compute_type)
            else:
                raise
        self.tokenizer = Tokenizer.from_file(tok)
        self.device = device
        self.compute_type = compute_type
        self._log = log

    # -- contexto ---------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.liberar()
        return False

    def liberar(self):
        """Solta a memoria (VRAM inclusive). Depois disso o objeto nao serve."""
        t = getattr(self, "tradutor", None)
        if t is not None:
            del self.tradutor
        import gc
        gc.collect()

    # -- idiomas ----------------------------------------------------------

    def idioma_suportado(self, iso2: str) -> bool:
        """True se o modelo REALMENTE conhece esse idioma.

        Nao basta estar no dicionario CODIGOS: o token do idioma precisa
        existir no vocabulario. E assim que descobrimos, sem adivinhar, se um
        idioma pouco comum (latim, por exemplo) esta coberto.
        """
        cod = codigo_nllb(iso2)
        if not cod:
            return False
        return self.tokenizer.token_to_id(cod) is not None

    def idiomas_suportados(self) -> list:
        return sorted(k for k in CODIGOS if self.idioma_suportado(k))

    # -- traducao ---------------------------------------------------------

    def _para_tokens(self, texto: str, origem_nllb: str) -> list:
        """Monta a entrada do encoder: [idioma_origem] ...texto... </s>.

        O tokenizer cru (biblioteca `tokenizers`, sem transformers) nao insere
        o token de idioma sozinho, entao fazemos isso a mao.
        """
        pecas = self.tokenizer.encode(texto, add_special_tokens=False).tokens
        return [origem_nllb] + pecas + ["</s>"]

    def traduzir(self, textos: Iterable[str], origem: str, destino: str,
                 lote: int = 16, beam: int = 2,
                 progress: Optional[ProgressCb] = None,
                 cancel: Optional[threading.Event] = None) -> list:
        """Traduz uma lista de textos de um idioma para outro.

        origem/destino sao codigos de duas letras (os mesmos do Whisper).
        """
        progress = progress or _noop
        textos = list(textos)
        if not textos:
            return []

        # Valida contra o VOCABULARIO do modelo, nao contra o mapa CODIGOS.
        # O mapa e uma tabela estatica e otimista (tem 'la', por exemplo); so o
        # tokenizer sabe quais tokens de idioma existem de fato. Sem esta
        # checagem o ctranslate2 aceita um token inexistente e devolve texto
        # silenciosamente errado, que e pior do que falhar.
        for iso2 in (origem, destino):
            if not self.idioma_suportado(iso2):
                raise ValueError(
                    f"o modelo de traducao nao cobre o idioma '{iso2}' "
                    f"(par pedido: {origem}->{destino})")
        o, d = codigo_nllb(origem), codigo_nllb(destino)

        saida = []
        for i in range(0, len(textos), lote):
            _checa_cancelamento(cancel)
            pedaco = textos[i:i + lote]
            fontes = [self._para_tokens(t, o) for t in pedaco]
            res = self.tradutor.translate_batch(
                fontes,
                target_prefix=[[d]] * len(fontes),
                beam_size=beam,
                max_batch_size=lote,
                # sem isso o modelo repete a ultima palavra em frases curtas
                repetition_penalty=1.1,
                no_repeat_ngram_size=3,
            )
            for r in res:
                # a primeira peca da hipotese e o token do idioma de destino
                pecas = r.hypotheses[0]
                if pecas and pecas[0] == d:
                    pecas = pecas[1:]
                ids = [self.tokenizer.token_to_id(p) for p in pecas]
                ids = [x for x in ids if x is not None]
                saida.append(self.tokenizer.decode(ids).strip())
            progress("traduzindo", min(i + lote, len(textos)), len(textos))
        return saida


def _tem_gpu() -> bool:
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# --------------------------------------------------------------------------
# Integracao com a saida do motor
# --------------------------------------------------------------------------

def traduzir_itens(itens: list, destino: str, caminho_modelo: str,
                   device: str = "auto",
                   progress: Optional[ProgressCb] = None,
                   cancel: Optional[threading.Event] = None,
                   log: Callable[[str], None] = _noop) -> list:
    """Traduz os itens aceitos do motor para `destino`.

    Devolve uma lista nova com os mesmos tempos e o texto traduzido. O campo
    'idioma_origem' guarda de onde veio; 'traduzido' diz se houve traducao de
    fato ou se a linha ja estava no idioma de destino.

    Agrupa por idioma de origem porque o NLLB traduz um par por vez: um filme
    en/it vira dois lotes, nao uma chamada por legenda.
    """
    progress = progress or _noop
    if not itens:
        return []

    por_idioma = {}
    for n, it in enumerate(itens):
        por_idioma.setdefault(it.get("idioma"), []).append((n, it))

    saida = [None] * len(itens)
    feitos = 0
    total = len(itens)

    with Tradutor(caminho_modelo, device=device, log=log) as t:
        if not t.idioma_suportado(destino):
            raise ValueError(
                f"o modelo de traducao nao cobre o idioma de destino "
                f"'{destino}'")

        for idioma, grupo in por_idioma.items():
            _checa_cancelamento(cancel)

            # ja esta no idioma de destino: copia, nao traduz. E o atalho que
            # torna barato traduzir um arquivo bilingue.
            if idioma == destino:
                for n, it in grupo:
                    novo = dict(it)
                    novo["idioma_origem"] = idioma
                    novo["traduzido"] = False
                    saida[n] = novo
                feitos += len(grupo)
                progress("traduzindo", feitos, total)
                log(f"  {idioma}: {len(grupo)} linhas ja no destino, copiadas")
                continue

            if not idioma or not t.idioma_suportado(idioma):
                # idioma desconhecido ou fora do modelo: mantem o original e
                # marca, em vez de inventar uma traducao ruim
                for n, it in grupo:
                    novo = dict(it)
                    novo["idioma_origem"] = idioma
                    novo["traduzido"] = False
                    novo["traducao_indisponivel"] = True
                    saida[n] = novo
                feitos += len(grupo)
                progress("traduzindo", feitos, total)
                log(f"  {idioma}: sem suporte no modelo, mantido no original")
                continue

            log(f"  {idioma} -> {destino}: {len(grupo)} linhas")
            textos = [it["texto"] for _, it in grupo]

            def avanco(_etapa, atual, _total, base=feitos):
                progress("traduzindo", base + atual, total)

            traduzidos = t.traduzir(textos, idioma, destino,
                                    progress=avanco, cancel=cancel)
            for (n, it), novo_texto in zip(grupo, traduzidos):
                novo = dict(it)
                novo["texto"] = novo_texto
                novo["idioma_origem"] = idioma
                novo["idioma"] = destino
                novo["traduzido"] = True
                saida[n] = novo
            feitos += len(grupo)
            progress("traduzindo", feitos, total)

    return saida


# --------------------------------------------------------------------------
# CLI de teste
# --------------------------------------------------------------------------

def main():
    import argparse
    import download_modelo

    p = argparse.ArgumentParser(description="Traduz texto com NLLB-200.")
    p.add_argument("texto", nargs="*", help="frases a traduzir")
    p.add_argument("--de", default="pt")
    p.add_argument("--para", default="en")
    p.add_argument("--modelo", default="nllb-600m")
    p.add_argument("--pasta-modelos", default="modelos")
    p.add_argument("--idiomas", action="store_true",
                   help="lista os idiomas que o modelo realmente cobre")
    a = p.parse_args()

    caminho = download_modelo.baixar_modelo(
        a.modelo, a.pasta_modelos,
        progress=lambda x, t: print(f"\r  {x/1e6:.0f} / {t/1e6:.0f} MB",
                                    end="", flush=True))
    print()

    with Tradutor(caminho, log=print) as t:
        print(f"device: {t.device} ({t.compute_type})")
        if a.idiomas:
            sup = t.idiomas_suportados()
            print(f"idiomas cobertos ({len(sup)}): {' '.join(sup)}")
            faltam = [k for k in CODIGOS if k not in sup]
            print(f"NAO cobertos: {' '.join(faltam) if faltam else '(nenhum)'}")
            return 0
        if not a.texto:
            p.error("informe ao menos uma frase, ou use --idiomas")
        for orig, trad in zip(a.texto, t.traduzir(a.texto, a.de, a.para)):
            print(f"  {a.de}: {orig}")
            print(f"  {a.para}: {trad}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
