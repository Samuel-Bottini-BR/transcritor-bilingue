#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor de transcricao bilingue com deteccao de idioma por trecho.

Arquitetura em quatro camadas, nesta ordem:
  1. VAD antes de tudo: fatia o audio em trechos de fala e nunca manda
     silencio, musica ou ruido para o modelo.
  2. Identificacao de idioma por trecho, restrita a um conjunto fechado:
     o classificador so pode responder dentro dos idiomas declarados. E isso
     que impede a saida em tamil/coreano/bengali quando o modelo ouve canto.
  3. Transcricao com o idioma travado por trecho e
     condition_on_previous_text=False (nao realimenta a saida anterior, que e
     a causa dos loops "Salamat Salamat Salamat...").
  4. Filtro de saida: log-prob baixo, no_speech_prob alto, repeticao em loop e
     alfabeto inesperado. O descartado vai para um relatorio com o motivo, nao
     some calado.

Este arquivo e importavel (a interface usa transcrever() com callback de
progresso e evento de cancelamento) e tambem roda por linha de comando.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from collections import Counter
from typing import Callable, Optional

# IMPORTANTE: registra as DLLs do CUDA antes de importar faster_whisper, senao
# o ctranslate2 nao encontra cublas/cudnn e a GPU nao funciona.
import cuda_setup  # noqa: F401

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

SR = 16000  # o Whisper trabalha a 16 kHz mono

# Callback de progresso: cb(etapa: str, atual: int, total: int).
# total <= 0 significa "etapa sem contador" (indeterminada).
ProgressCb = Callable[[str, int, int], None]


class CanceladoError(Exception):
    """Levantada quando o usuario cancela no meio do processo."""


def _checa_cancelamento(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise CanceladoError()


def _noop(*_args, **_kwargs) -> None:
    pass


# --------------------------------------------------------------------------
# Deteccao de GPU e carregamento do modelo
# --------------------------------------------------------------------------

def gpu_disponivel() -> bool:
    """True se o ctranslate2 enxerga uma GPU CUDA utilizavel.

    Usamos o proprio ctranslate2 (nao o torch) porque e ele quem executa o
    modelo; assim a deteccao reflete o que de fato vai rodar.
    """
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# Ordem de fallback de precisao por device. No 4 GB da GTX 1650 o large-v3 em
# float16 estoura a memoria; int8_float16 cabe com perda pequena. Tentamos do
# melhor para o mais economico ate um carregar.
_PRECISOES = {
    "cuda": ["float16", "int8_float16", "int8"],
    "cpu": ["int8", "float32"],
}


def carregar_modelo(nome_modelo: str, device: str,
                    compute_type: Optional[str] = None,
                    pasta_modelos: Optional[str] = None,
                    log: Callable[[str], None] = _noop):
    """Carrega o WhisperModel tentando precisoes ate uma caber na memoria.

    Retorna (modelo, device_real, compute_type_real).
    """
    if device == "auto":
        device = "cuda" if gpu_disponivel() else "cpu"

    tentativas = [compute_type] if compute_type else list(_PRECISOES[device])

    ultimo_erro = None
    for ct in tentativas:
        try:
            log(f"carregando modelo {nome_modelo} em {device} ({ct})...")
            modelo = WhisperModel(
                nome_modelo, device=device, compute_type=ct,
                download_root=pasta_modelos,
            )
            return modelo, device, ct
        except Exception as e:  # OOM, precisao nao suportada, etc.
            ultimo_erro = e
            log(f"  falhou com {ct}: {e}")

    # Se pediram GPU e nenhuma precisao coube, cai para CPU como ultimo recurso.
    if device == "cuda":
        log("  GPU nao coube; caindo para CPU (vai ficar lento)")
        return carregar_modelo(nome_modelo, "cpu", None, pasta_modelos, log)

    raise RuntimeError(f"nao foi possivel carregar o modelo: {ultimo_erro}")


# --------------------------------------------------------------------------
# 1. VAD: fatiar o audio em trechos de fala
# --------------------------------------------------------------------------

def fatiar(audio, min_silencio_ms=500, min_fala_ms=250):
    """Retorna trechos de fala como (inicio_s, fim_s)."""
    opts = VadOptions(
        min_silence_duration_ms=min_silencio_ms,
        min_speech_duration_ms=min_fala_ms,
        speech_pad_ms=200,
    )
    marcas = get_speech_timestamps(audio, opts)
    return [(m["start"] / SR, m["end"] / SR) for m in marcas]


def agrupar(trechos, max_dur=24.0, max_gap=0.7):
    """Junta trechos vizinhos em blocos maiores.

    Trecho curto demais atrapalha a deteccao de idioma; trecho longo demais
    aumenta a chance de o bloco misturar os dois idiomas.
    """
    if not trechos:
        return []
    saida = [list(trechos[0])]
    for ini, fim in trechos[1:]:
        if ini - saida[-1][1] <= max_gap and fim - saida[-1][0] <= max_dur:
            saida[-1][1] = fim
        else:
            saida.append([ini, fim])
    return [tuple(x) for x in saida]


# --------------------------------------------------------------------------
# 2. Identificacao de idioma restrita a um conjunto fechado
# --------------------------------------------------------------------------

def idioma_do_trecho(modelo, audio, ini, fim, permitidos):
    """Decide o idioma olhando so para os idiomas permitidos.

    Essa restricao e o que impede o modelo de responder 'tamil' ou 'coreano'
    quando ouve canto religioso ou grito. Retorna (idioma, confianca) onde a
    confianca e a fatia do idioma escolhido dentro do conjunto permitido.
    """
    corte = audio[int(ini * SR):int(fim * SR)]
    if len(corte) < SR // 2:  # abaixo de 0,5s a deteccao nao e confiavel
        return None, 0.0
    _, _, todas = modelo.detect_language(corte)
    probs = dict(todas)
    pontuacao = {lg: probs.get(lg, 0.0) for lg in permitidos}
    melhor = max(pontuacao, key=pontuacao.get)
    total = sum(pontuacao.values()) or 1e-9
    return melhor, pontuacao[melhor] / total


def suavizar(blocos, dur_minima=1.2):
    """Trecho curto (<1,2s) ou inseguro herda o idioma do vizinho.

    Abaixo de ~1,2s a deteccao e pouco confiavel; e melhor herdar do que
    deixar o bloco decidir sozinho e errar.
    """
    for i, b in enumerate(blocos):
        curto = (b["fim"] - b["ini"]) < dur_minima
        inseguro = b["conf_idioma"] < 0.65
        if not (curto or inseguro):
            continue
        vizinhos = []
        if i > 0:
            vizinhos.append(blocos[i - 1]["idioma"])
        if i + 1 < len(blocos):
            vizinhos.append(blocos[i + 1]["idioma"])
        vizinhos = [v for v in vizinhos if v]
        if vizinhos:
            b["idioma"] = Counter(vizinhos).most_common(1)[0][0]
            b["herdado"] = True
    return blocos


# --------------------------------------------------------------------------
# 3. Filtro de alucinacao
# --------------------------------------------------------------------------

# Quantas vezes o MESMO texto pode aparecer dentro de um unico bloco antes de
# virar descarte. 1 = so a primeira ocorrencia passa.
#
# Medido no Stromboli (1950): 29 segmentos identicos num unico bloco de 24s. O
# filtro de texto nao pegava nenhum, porque cada segmento, isolado, e uma frase
# curta e normal. A repeticao so aparece quando se olham os irmaos.
MAX_REPETICOES_BLOCO = 1


def _chave_repeticao(texto):
    """Normaliza para comparar segmentos: minusculas, sem pontuacao nem espaco
    duplicado. Assim 'Thank you.' e 'thank you' contam como o mesmo texto."""
    t = re.sub(r"[^\w\s]", "", texto.lower())
    return re.sub(r"\s+", " ", t).strip()


def marcar_repeticoes(textos, maximo=MAX_REPETICOES_BLOCO):
    """Dados os textos de UM bloco, na ordem, diz quais sao repeticao.

    Retorna uma lista de bool do mesmo tamanho: True = descartar. A primeira
    ocorrencia sempre passa; a partir da (maximo+1)-esima, descarta.
    """
    vistos = Counter()
    saida = []
    for t in textos:
        chave = _chave_repeticao(t)
        if not chave:            # texto vazio ou so pontuacao: outro filtro trata
            saida.append(False)
            continue
        vistos[chave] += 1
        saida.append(vistos[chave] > maximo)
    return saida


def parece_alucinacao(texto, logprob, no_speech):
    """Pega os padroes classicos de saida inventada.

    Retorna o motivo (str) do descarte, ou None se o texto passa.
    """
    t = texto.strip()
    if not t:
        return "vazio"
    if no_speech > 0.6:
        return "provavelmente sem fala"
    if logprob < -1.0:
        return "confianca baixa"

    palavras = re.findall(r"\w+", t.lower())
    # loop de repeticao: uma unica palavra domina o trecho
    if len(palavras) >= 4:
        mais_comum = Counter(palavras).most_common(1)[0][1]
        if mais_comum / len(palavras) > 0.5:
            return "repeticao em loop"

    # mesmo bloco de caracteres repetido em sequencia (ex.: "lalala lalala...")
    if re.search(r"(.{3,30}?)\1{3,}", t):
        return "repeticao em loop"

    # caracteres fora do alfabeto latino num audio que deveria ser latino
    # (en/it): pega a saida em tamil, devanagari, coreano, etc.
    latinos = sum(1 for c in t if c.isalpha() and ord(c) < 0x250)
    alfabeticos = sum(1 for c in t if c.isalpha())
    if alfabeticos and latinos / alfabeticos < 0.5:
        return "alfabeto inesperado"

    return None


# --------------------------------------------------------------------------
# 4. Pipeline
# --------------------------------------------------------------------------

def transcrever(caminho, permitidos, nome_modelo="large-v3", device="auto",
                compute_type=None, pasta_modelos=None,
                modelo_idioma=None,
                progress: Optional[ProgressCb] = None,
                cancel: Optional[threading.Event] = None,
                log: Callable[[str], None] = _noop):
    """Roda o pipeline completo e devolve (aceitos, descartados, info).

    modelo_idioma: se informado (ex.: caminho do modelo pequeno), a
    identificacao de idioma usa esse modelo leve e a transcricao usa
    nome_modelo. Como o idioma nao precisa da precisao do modelo grande (o
    pequeno acerta en/it com folga), isso economiza um encode caro de 30s por
    bloco no modelo grande. Os modelos sao carregados em duas passagens para
    nao disputar a memoria da GPU.

    progress(etapa, atual, total) e chamado durante o processo.
    cancel e um threading.Event; se setado, levanta CanceladoError.
    """
    import gc
    progress = progress or _noop
    dois_passos = bool(modelo_idioma) and modelo_idioma != nome_modelo

    progress("decodificando", 0, 0)
    log("decodificando audio...")
    audio = decode_audio(caminho, sampling_rate=SR)
    dur = len(audio) / SR
    log(f"  {dur/60:.1f} min")
    _checa_cancelamento(cancel)

    progress("detectando fala", 0, 0)
    log("detectando fala (VAD)...")
    blocos_tempo = agrupar(fatiar(audio))
    total = len(blocos_tempo)
    log(f"  {total} blocos de fala")
    _checa_cancelamento(cancel)

    # --- Passagem 1: identificacao de idioma ---
    log("identificando idioma por bloco...")
    if dois_passos:
        modelo_lg, device_real, _ = carregar_modelo(
            modelo_idioma, device, None, pasta_modelos, log)
    else:
        modelo_lg, device_real, ct_real = carregar_modelo(
            nome_modelo, device, compute_type, pasta_modelos, log)

    blocos = []
    for n, (ini, fim) in enumerate(blocos_tempo, 1):
        _checa_cancelamento(cancel)
        lg, conf = idioma_do_trecho(modelo_lg, audio, ini, fim, permitidos)
        blocos.append({"ini": ini, "fim": fim, "idioma": lg,
                       "conf_idioma": conf, "herdado": False})
        progress("identificando idioma", n, total)
    blocos = suavizar(blocos)

    contagem = Counter(b["idioma"] for b in blocos)
    log("  " + "  ".join(f"{k}: {v}" for k, v in contagem.items()))

    # --- Passagem 2: transcricao (troca o modelo se for de dois passos) ---
    if dois_passos:
        del modelo_lg
        gc.collect()  # libera a VRAM do modelo pequeno antes de carregar o grande
        modelo, _, ct_real = carregar_modelo(
            nome_modelo, device, compute_type, pasta_modelos, log)
    else:
        modelo = modelo_lg

    log("transcrevendo...")
    resultado, descartados = [], []
    for n, b in enumerate(blocos, 1):
        _checa_cancelamento(cancel)
        progress("transcrevendo", n, total)
        if not b["idioma"]:
            continue
        corte = audio[int(b["ini"] * SR):int(b["fim"] * SR)]
        segmentos, _ = modelo.transcribe(
            corte,
            language=b["idioma"],
            beam_size=5,
            # a chave contra loop de repeticao: nao realimenta o texto anterior
            condition_on_previous_text=False,
            temperature=[0.0, 0.2, 0.4, 0.6],
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
            word_timestamps=False,
        )
        # materializa a lista: o bloco tem no maximo ~24s, entao sao poucos
        # segmentos. Sem isso nao da para olhar os irmaos antes de decidir, que
        # e justamente o que faltava no filtro.
        segs = list(segmentos)
        repetido = marcar_repeticoes([s.text for s in segs])
        for s, e_repeticao in zip(segs, repetido):
            motivo = parece_alucinacao(s.text, s.avg_logprob, s.no_speech_prob)
            if not motivo and e_repeticao:
                motivo = "repeticao no bloco"
            # s.start/s.end sao relativos ao corte, que comeca em b["ini"];
            # somar b["ini"] devolve o tempo absoluto no filme.
            # grampeia inicio e fim aos limites do bloco (o Whisper as vezes
            # devolve tempos fora do audio do bloco).
            ini_abs = min(max(b["ini"] + s.start, b["ini"]), b["fim"])
            fim_abs = min(max(b["ini"] + s.end, b["ini"]), b["fim"])
            # garante duracao minima: as vezes o Whisper da fim<=ini na borda do
            # bloco. Puxa o inicio para tras (dentro do bloco) em vez de gerar
            # uma legenda invalida.
            if fim_abs - ini_abs < 0.2:
                fim_abs = min(ini_abs + 0.2, b["fim"])
                ini_abs = max(b["ini"], fim_abs - 0.2)
            item = {
                "ini": ini_abs,
                "fim": fim_abs,
                "texto": s.text.strip(),
                "idioma": b["idioma"],
                "conf_idioma": round(b["conf_idioma"], 3),
                "idioma_herdado": b["herdado"],
                "logprob": round(s.avg_logprob, 3),
                "no_speech": round(s.no_speech_prob, 3),
            }
            if motivo:
                item["descartado_por"] = motivo
                descartados.append(item)
            else:
                resultado.append(item)

    info = {
        "device": device_real,
        "compute_type": ct_real,
        "modelo": nome_modelo,
        "duracao_s": dur,
        "blocos": len(blocos),
        "aceitos": len(resultado),
        "descartados": len(descartados),
    }
    return resultado, descartados, info


# --------------------------------------------------------------------------
# 5. Saida
# --------------------------------------------------------------------------

def ts(x):
    ms = int(round(x * 1000))
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


def escrever_srt(itens, destino, marcar=False, dur_min=0.4):
    """Escreve o SRT. Rede de seguranca final nos tempos: garante duracao
    minima (fim > ini) e evita que uma legenda invada a seguinte, mesmo que os
    tempos vindos do modelo estejam degenerados."""
    linhas = []
    for i, (ini, fim, it) in enumerate(_tempos_limpos(itens, dur_min)):
        txt = it["texto"]
        if marcar:
            txt = f"[{(it.get('idioma') or '??').upper()}] {txt}"
        linhas.append(f"{i+1}\n{ts(ini)} --> {ts(fim)}\n{txt}\n")
    with open(destino, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(linhas))


def _tempos_limpos(itens, dur_min=0.4):
    """Ordena e conserta os tempos: duracao minima e sem invadir a proxima.

    Extraido de escrever_srt para que VTT e SRT apliquem exatamente as mesmas
    correcoes - senao os dois formatos saem com tempos diferentes.
    """
    s = sorted(itens, key=lambda x: x["ini"])
    saida = []
    for i, it in enumerate(s):
        ini = it["ini"]
        fim = max(it["fim"], ini + dur_min)
        if i + 1 < len(s):
            prox = s[i + 1]["ini"]
            if fim > prox:
                fim = max(ini + 0.05, prox - 0.001)
        saida.append((ini, fim, it))
    return saida


def escrever_vtt(itens, destino, marcar=False, dur_min=0.4):
    """WebVTT: mesma legenda do SRT, formato que navegador e web player leem.

    Diferencas para o SRT: cabecalho WEBVTT, ponto em vez de virgula nos
    milissegundos, e sem numero de sequencia.
    """
    linhas = ["WEBVTT", ""]
    for ini, fim, it in _tempos_limpos(itens, dur_min):
        txt = it["texto"]
        if marcar:
            txt = f"[{(it.get('idioma') or '??').upper()}] {txt}"
        linhas.append(f"{ts(ini).replace(',', '.')} --> "
                      f"{ts(fim).replace(',', '.')}")
        linhas.append(txt)
        linhas.append("")
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(linhas))


def escrever_txt(itens, destino, marcar=False):
    """So o texto corrido, sem tempos. Serve para ler, buscar ou colar."""
    linhas = []
    for it in sorted(itens, key=lambda x: x["ini"]):
        txt = it["texto"].strip()
        if not txt:
            continue
        if marcar:
            txt = f"[{(it.get('idioma') or '??').upper()}] {txt}"
        linhas.append(txt)
    with open(destino, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(linhas) + "\n")


def escrever_relatorio(aceitos, descartados, info, destino):
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({"info": info, "aceitos": aceitos, "descartados": descartados},
                  f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Transcritor bilingue por trecho.")
    p.add_argument("entrada")
    p.add_argument("--idiomas", nargs="+", default=["en", "it"],
                   help="conjunto fechado de idiomas possiveis")
    p.add_argument("--saida", default=None)
    p.add_argument("--modelo", default="large-v3")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--compute-type", default=None,
                   help="ex.: float16, int8_float16, int8")
    p.add_argument("--pasta-modelos", default=None,
                   help="onde baixar/guardar os pesos")
    p.add_argument("--marcar-idioma", action="store_true",
                   help="prefixa cada linha com [EN] ou [IT]")
    a = p.parse_args()

    saida = a.saida or os.path.splitext(a.entrada)[0] + ".srt"

    def log(msg):
        print(msg, file=sys.stderr)

    def progresso(etapa, atual, total):
        if total:
            print(f"\r{etapa}: {atual}/{total}   ", end="", file=sys.stderr)
        else:
            print(f"{etapa}...", file=sys.stderr)

    aceitos, descartados, info = transcrever(
        a.entrada, a.idiomas, a.modelo, a.device, a.compute_type,
        a.pasta_modelos, progress=progresso, log=log)
    print("", file=sys.stderr)

    escrever_srt(aceitos, saida, a.marcar_idioma)
    relatorio = os.path.splitext(saida)[0] + "_relatorio.json"
    escrever_relatorio(aceitos, descartados, info, relatorio)

    print(f"\n{len(aceitos)} legendas -> {saida}", file=sys.stderr)
    print(f"{len(descartados)} descartadas -> {relatorio}", file=sys.stderr)
    if descartados:
        motivos = Counter(d["descartado_por"] for d in descartados)
        for k, v in motivos.most_common():
            print(f"    {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
