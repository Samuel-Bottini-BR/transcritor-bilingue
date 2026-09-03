#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Formatacao da legenda: transforma texto correto em legenda legivel.

O motor devolve o texto que o modelo ouviu, com os tempos do bloco de fala.
Isso ainda nao e uma legenda: medindo a saida real do Stromboli e do Breviarium,
77% das linhas passavam de 42 caracteres e algumas ficavam 18 segundos na tela.

Os limites abaixo sao os usados na legendagem profissional (guias da EBU e das
plataformas de streaming):

  42 caracteres por linha, no maximo 2 linhas
  ate 7 segundos na tela, no minimo ~0,83
  ate ~17 caracteres por segundo de leitura
  folga minima de ~0,08 s entre duas legendas (2 quadros a 24 fps)

Tres operacoes, nesta ordem:
  1. dividir  - legenda longa demais vira duas ou mais, com o tempo repartido
  2. quebrar  - cada uma ganha ate duas linhas equilibradas
  3. folgar   - garante o respiro entre legendas vizinhas

Tudo aqui e logica pura: nao usa modelo, nao usa GPU, e roda em milissegundos.
"""

from __future__ import annotations

import re

MAX_LINHA = 42        # caracteres por linha
MAX_LINHAS = 2        # linhas por legenda
MAX_DUR = 7.0         # segundos na tela
MIN_DUR = 0.833       # 5/6 de segundo
MIN_GAP = 0.083       # 2 quadros a 24 fps
MAX_CPS = 17.0        # caracteres por segundo (velocidade de leitura)

# Palavras curtas que nao devem FECHAR uma linha: quebrar antes delas deixa a
# leitura mais natural do que separa-las do que vem depois. Portugues, ingles e
# italiano juntos - o app e bilingue, e o custo de manter tudo numa lista so e
# menor que o de descobrir o idioma aqui dentro.
_GRUDAM_NO_SEGUINTE = {
    # artigos e preposicoes
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "em", "no", "na", "nos", "nas", "ao", "aos", "para", "por", "com",
    "sem", "sob", "sobre", "entre", "ate", "desde", "que", "se", "e", "ou",
    "mas", "the", "an", "of", "to", "in", "on", "at", "for", "with", "and",
    "or", "but", "il", "lo", "la", "gli", "le", "di", "del", "della", "dei",
    "nel", "nella", "con", "per", "tra", "fra", "che", "e", "ma", "un", "una",
}

_FIM_FRASE = ".!?…"
_PAUSA = ",;:"


def _palavras(texto: str) -> list:
    return [p for p in re.split(r"\s+", texto.strip()) if p]


# --------------------------------------------------------------------------
# 1. Quebra em linhas
# --------------------------------------------------------------------------

def _nota_do_corte(antes: str, depois: str, esquerda: int, direita: int) -> float:
    """Quanto vale cortar entre estas duas palavras. Maior e melhor.

    Combina dois criterios: a qualidade gramatical do ponto de corte e o
    equilibrio entre as duas metades - uma linha de 40 e outra de 3 e feia
    mesmo que o corte caia numa virgula.
    """
    nota = 0.0
    ultimo = antes[-1:] if antes else ""
    if ultimo in _FIM_FRASE:
        nota += 6.0
    elif ultimo in _PAUSA:
        nota += 4.0
    limpa = re.sub(r"[^\w']", "", antes.lower())
    if limpa in _GRUDAM_NO_SEGUINTE:
        nota -= 3.0          # nao deixe 'de' sozinho no fim da linha
    seguinte = re.sub(r"[^\w']", "", depois.lower())
    if seguinte in _GRUDAM_NO_SEGUINTE:
        nota += 0.5          # cortar ANTES de preposicao e bom
    # equilibrio: 1.0 quando as metades sao iguais, 0 quando uma domina
    total = esquerda + direita
    if total:
        nota += 3.0 * (1.0 - abs(esquerda - direita) / total)
    return nota


def quebrar_linhas(texto: str, max_linha: int = MAX_LINHA,
                   max_linhas: int = MAX_LINHAS) -> list:
    """Distribui o texto em ate `max_linhas` linhas de ate `max_linha`.

    Se nao couber, devolve o melhor arranjo possivel - quem garante que cabe e
    dividir(), chamado antes.
    """
    texto = " ".join(texto.split())
    if len(texto) <= max_linha:
        return [texto]

    palavras = _palavras(texto)
    if len(palavras) < 2:
        return [texto]

    if max_linhas <= 2:
        # escolhe UM ponto de corte, o de melhor nota entre os viaveis
        melhor, melhor_nota = None, float("-inf")
        for i in range(1, len(palavras)):
            esq = " ".join(palavras[:i])
            dir_ = " ".join(palavras[i:])
            if len(esq) > max_linha or len(dir_) > max_linha:
                # ainda assim consideramos, com penalidade, para nunca voltar
                # sem resposta
                nota = _nota_do_corte(palavras[i - 1], palavras[i],
                                      len(esq), len(dir_)) - 20.0
            else:
                nota = _nota_do_corte(palavras[i - 1], palavras[i],
                                      len(esq), len(dir_))
            if nota > melhor_nota:
                melhor, melhor_nota = i, nota
        return [" ".join(palavras[:melhor]), " ".join(palavras[melhor:])]

    # mais de duas linhas: enche greedy, que e suficiente para .txt/preview
    linhas, atual = [], ""
    for p in palavras:
        if not atual:
            atual = p
        elif len(atual) + 1 + len(p) <= max_linha:
            atual += " " + p
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


# --------------------------------------------------------------------------
# 2. Divisao de legenda longa
# --------------------------------------------------------------------------

# Folga na conta de quanto cabe. Em teoria cabem 42x2 = 84 caracteres, mas so
# se existir fronteira de palavra exatamente em 41/42 - o que quase nunca
# acontece. Medindo a saida real, textos de 70 a 84 caracteres eram os que
# sobravam acima do limite. Reservar ~12% resolve.
FOLGA_CABE = 0.88


def _quantas_partes(texto: str, dur: float, max_linha: int,
                    max_linhas: int) -> int:
    """Em quantas legendas este item precisa virar."""
    cabe = int(max_linha * max_linhas * FOLGA_CABE)
    por_texto = -(-len(texto) // cabe)                 # teto da divisao
    por_tempo = -(-int(dur * 1000) // int(MAX_DUR * 1000))
    por_leitura = -(-int(len(texto)) // max(1, int(MAX_CPS * MAX_DUR)))
    return max(1, por_texto, por_tempo, por_leitura)


def _cortar_em(palavras: list, partes: int) -> list:
    """Divide a lista de palavras em `partes` grupos, cortando em ponto bom.

    O alvo e o corte proporcional; a partir dele procuramos o melhor ponto
    gramatical numa janela em volta, para nao partir no meio de uma oracao.
    """
    if partes <= 1 or len(palavras) <= partes:
        return [palavras]

    comprimentos = [len(p) for p in palavras]
    total = sum(comprimentos) + len(palavras) - 1
    alvo = total / partes

    cortes, acumulado, proximo = [], 0, alvo
    for i, c in enumerate(comprimentos[:-1]):
        acumulado += c + 1
        if acumulado >= proximo and len(cortes) < partes - 1:
            # janela de +-3 palavras em torno do ponto proporcional
            melhor, melhor_nota = i + 1, float("-inf")
            for j in range(max(1, i - 2), min(len(palavras), i + 4)):
                if cortes and j <= cortes[-1]:
                    continue
                nota = _nota_do_corte(palavras[j - 1], palavras[j], 1, 1)
                # desempate pela proximidade do ponto ideal
                nota -= abs(j - (i + 1)) * 0.4
                if nota > melhor_nota:
                    melhor, melhor_nota = j, nota
            cortes.append(melhor)
            proximo += alvo

    grupos, anterior = [], 0
    for c in cortes:
        if c > anterior:
            grupos.append(palavras[anterior:c])
            anterior = c
    grupos.append(palavras[anterior:])
    return [g for g in grupos if g]


def _precisa_dividir(texto: str, dur: float, max_linha: int,
                     max_linhas: int) -> bool:
    return (len(texto) > max_linha * max_linhas) or (dur > MAX_DUR)


def dividir(item: dict, max_linha: int = MAX_LINHA,
            max_linhas: int = MAX_LINHAS, _fundo: int = 0) -> list:
    """Uma legenda longa vira varias, com o tempo repartido pelo texto.

    Reexamina o resultado: os cortes procuram ponto gramatical bom, o que
    desloca as fronteiras em relacao ao corte proporcional e pode deixar uma
    parte ainda grande. Sem esta segunda passada sobravam linhas acima de 42
    caracteres na medicao real.
    """
    texto = " ".join(item["texto"].split())
    dur = max(0.0, item["fim"] - item["ini"])

    def so_um():
        novo = dict(item)
        novo["texto"] = texto
        return [novo]

    partes = _quantas_partes(texto, dur, max_linha, max_linhas)
    if partes <= 1:
        return so_um()

    grupos = _cortar_em(_palavras(texto), partes)
    if len(grupos) <= 1:
        return so_um()

    textos = [" ".join(g) for g in grupos]
    pesos = [len(t) for t in textos]
    soma = sum(pesos) or 1

    saida, inicio = [], item["ini"]
    for i, (t, peso) in enumerate(zip(textos, pesos)):
        fatia = dur * peso / soma
        fim = item["fim"] if i == len(textos) - 1 else inicio + fatia
        novo = dict(item)
        novo["texto"] = t
        novo["ini"] = inicio
        novo["fim"] = max(fim, inicio + 0.05)
        # a parte ainda nao coube: divide de novo. O limite de profundidade
        # evita laco infinito quando o texto e uma palavra so, gigante.
        if _fundo < 3 and _precisa_dividir(t, novo["fim"] - novo["ini"],
                                           max_linha, max_linhas):
            saida.extend(dividir(novo, max_linha, max_linhas, _fundo + 1))
        else:
            saida.append(novo)
        inicio = novo["fim"]
    return saida


# --------------------------------------------------------------------------
# 3. Folga entre legendas
# --------------------------------------------------------------------------

def _teto(s: list, i: int, gap: float) -> float:
    """Ate onde a legenda i pode se estender sem encostar na seguinte."""
    if i + 1 < len(s):
        return s[i + 1]["ini"] - gap
    return s[i]["fim"] + 3.0        # ultima: pode sobrar tempo depois da fala


def folgar(itens: list, gap: float = MIN_GAP, min_dur: float = MIN_DUR) -> list:
    """Garante respiro entre legendas vizinhas, sem inverter a ordem.

    Move o FIM, nunca o inicio: atrasar o inicio dessincronizaria a legenda da
    fala. Duas passadas - primeiro abre a folga onde falta, depois estica quem
    ficou curta demais, mas so ate onde houver espaco livre.
    """
    s = sorted((dict(i) for i in itens), key=lambda x: x["ini"])
    for i in range(len(s) - 1):
        limite = s[i + 1]["ini"] - gap
        if s[i]["fim"] > limite:
            s[i]["fim"] = max(limite, s[i]["ini"] + 0.2)
    for i, it in enumerate(s):
        if it["fim"] - it["ini"] < min_dur:
            # estica ate o minimo, sem invadir a proxima
            it["fim"] = max(it["fim"], min(it["ini"] + min_dur,
                                           _teto(s, i, gap)))
    return s


def esticar(itens: list, gap: float = MIN_GAP, max_cps: float = MAX_CPS) -> list:
    """Alivia a velocidade de leitura usando o silencio que vem depois.

    Legenda densa fica pouco tempo na tela porque a fala foi rapida; se houver
    pausa em seguida, prolongar o fim da mais tempo de leitura sem tirar a
    legenda do lugar. Tecnica padrao de legendagem, e o unico jeito de baixar
    o CPS sem cortar texto.
    """
    s = sorted((dict(i) for i in itens), key=lambda x: x["ini"])
    for i, it in enumerate(s):
        n = len(it["texto"].replace("\n", " "))
        precisa = n / max_cps
        if it["fim"] - it["ini"] >= precisa:
            continue
        alvo = min(it["ini"] + precisa, it["ini"] + MAX_DUR)
        it["fim"] = max(it["fim"], min(alvo, _teto(s, i, gap)))
    return s


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def formatar(itens: list, max_linha: int = MAX_LINHA,
             max_linhas: int = MAX_LINHAS, gap: float = MIN_GAP) -> list:
    """Dividir -> quebrar -> folgar. Devolve itens novos, nao mexe nos de fora.

    O campo 'texto' sai com '\\n' entre as linhas, que e como o SRT e o VTT
    representam a quebra.
    """
    if not itens:
        return []
    partidos = []
    for it in itens:
        if not (it.get("texto") or "").strip():
            continue
        partidos.extend(dividir(it, max_linha, max_linhas))
    # verificacao final: se mesmo depois da divisao a quebra nao couber, o item
    # e dividido de novo. Sem esta passada, a conta de "quantas partes" precisa
    # acertar de primeira, e ela depende de onde caem as fronteiras de palavra.
    conferidos, guarda = [], 0
    for it in partidos:
        linhas = quebrar_linhas(it["texto"], max_linha, max_linhas)
        if all(len(l) <= max_linha for l in linhas) or guarda > 400:
            conferidos.append(it)
            continue
        guarda += 1
        forcado = dict(it)
        # forca ao menos duas partes reduzindo o alvo de cabimento
        pedacos = dividir(forcado, max_linha, max(1, max_linhas - 1))
        conferidos.extend(pedacos if len(pedacos) > 1 else [it])

    ajustados = esticar(folgar(conferidos, gap), gap)
    for it in ajustados:
        it["texto"] = "\n".join(quebrar_linhas(it["texto"], max_linha,
                                               max_linhas))
    return ajustados


def medir(itens: list) -> dict:
    """Numeros de conformidade, para comparar antes e depois."""
    if not itens:
        return {}
    n = len(itens)
    linhas_longas = sum(
        1 for i in itens
        if any(len(l) > MAX_LINHA for l in i["texto"].split("\n")))
    muitas_linhas = sum(1 for i in itens if i["texto"].count("\n") + 1 > MAX_LINHAS)
    # mesma tolerancia de 1 microssegundo usada na folga: uma legenda com
    # exatamente MIN_DUR sai como 0.8330000000000001 ou 0.8329999 em binario
    longas = sum(1 for i in itens if i["fim"] - i["ini"] > MAX_DUR + 1e-6)
    curtas = sum(1 for i in itens if i["fim"] - i["ini"] < MIN_DUR - 1e-6)
    cps = [len(i["texto"].replace("\n", " ")) / max(0.001, i["fim"] - i["ini"])
           for i in itens]
    rapidas = sum(1 for c in cps if c > 21.0)
    s = sorted(itens, key=lambda x: x["ini"])
    # tolerancia de 1 microssegundo: 5.7 - 0.083 nao da exatamente 5.617 em
    # binario, e sem folga aqui a medicao acusaria falta de folga onde ela
    # existe. O SRT so tem resolucao de milissegundo de qualquer forma.
    colados = sum(1 for a, b in zip(s, s[1:])
                  if b["ini"] - a["fim"] < MIN_GAP - 1e-6)
    sobrep = sum(1 for a, b in zip(s, s[1:]) if b["ini"] < a["fim"])
    return {"n": n, "linha_longa": linhas_longas, "muitas_linhas": muitas_linhas,
            "duracao_longa": longas, "duracao_curta": curtas,
            "leitura_rapida": rapidas, "sem_folga": colados,
            "sobrepostas": sobrep,
            "cps_mediano": sorted(cps)[len(cps) // 2]}
