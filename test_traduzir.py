# -*- coding: utf-8 -*-
"""Testes do tradutor. Exige o modelo nllb-600m baixado em ./modelos.

Nao comparamos com uma traducao exata (a saida varia com beam/versao); testamos
PROPRIEDADES: mudou de idioma, nao veio vazio, preservou tempos, respeitou o
atalho de idioma igual, e falhou de forma limpa onde tem que falhar.
"""

import threading
import time

import download_modelo
import traduzir

PASTA = "modelos"
falhas = []


def checa(nome, condicao, detalhe=""):
    marca = "OK " if condicao else "FALHOU"
    if not condicao:
        falhas.append(nome)
    print(f"[{marca}] {nome}" + (f"  {detalhe}" if detalhe else ""))


def main():
    print("=== preparando ===")
    caminho = download_modelo.baixar_modelo("nllb-600m", PASTA)
    checa("modelo disponivel offline",
          download_modelo.modelo_ja_baixado("nllb-600m", PASTA))

    t0 = time.time()
    tr = traduzir.Tradutor(caminho, log=lambda m: None)
    print(f"    carregado em {time.time()-t0:.1f}s "
          f"({tr.device} {tr.compute_type})\n")

    print("=== 1. idiomas ===")
    checa("portugues suportado", tr.idioma_suportado("pt"))
    checa("italiano suportado", tr.idioma_suportado("it"))
    checa("ingles suportado", tr.idioma_suportado("en"))
    checa("latim NAO suportado (esperado)", not tr.idioma_suportado("la"))
    checa("idioma inexistente da False", not tr.idioma_suportado("xx"))
    checa("mapa de codigos", traduzir.codigo_nllb("pt") == "por_Latn")

    print("\n=== 2. traducao basica ===")
    casos = [
        ("pt", "en", "O barco sai amanhã de manhã.", ("boat", "ship", "leaves",
                                                      "tomorrow", "morning")),
        ("it", "en", "Non ho mai visto un posto così bello.", ("never", "seen",
                                                               "place",
                                                               "beautiful")),
        ("en", "pt", "The house is very old.", ("casa", "velha", "antiga")),
        ("it", "pt", "Dove vai adesso?", ("onde", "vai", "agora")),
    ]
    for de, para, texto, esperadas in casos:
        got = tr.traduzir([texto], de, para)[0]
        print(f"    {de}->{para}: {texto!r}")
        print(f"              -> {got!r}")
        checa(f"traduziu {de}->{para} (nao vazio)", bool(got.strip()))
        checa(f"traduziu {de}->{para} (mudou o texto)",
              got.strip().lower() != texto.strip().lower())
        achou = [p for p in esperadas if p.lower() in got.lower()]
        checa(f"traduziu {de}->{para} (sentido plausivel)", bool(achou),
              f"achou {achou}")

    print("\n=== 3. lote ===")
    muitos = [f"Esta e a frase numero {i}." for i in range(1, 26)]
    saida = tr.traduzir(muitos, "pt", "en", lote=8)
    checa("lote devolve o mesmo tamanho", len(saida) == len(muitos),
          f"{len(saida)} de {len(muitos)}")
    checa("nenhuma linha vazia no lote", all(s.strip() for s in saida))

    print("\n=== 4. par invalido ===")
    try:
        tr.traduzir(["teste"], "pt", "la")
        checa("par nao suportado levanta erro", False)
    except ValueError:
        checa("par nao suportado levanta ValueError", True)

    print("\n=== 5. entrada vazia ===")
    checa("lista vazia devolve lista vazia", tr.traduzir([], "pt", "en") == [])

    print("\n=== 6. cancelamento ===")
    evento = threading.Event()
    evento.set()
    try:
        tr.traduzir(["uma frase qualquer"] * 40, "pt", "en", cancel=evento)
        checa("cancelamento interrompe", False)
    except traduzir.CanceladoError:
        checa("cancelamento levanta CanceladoError", True)

    tr.liberar()

    print("\n=== 7. integracao com a saida do motor ===")
    itens = [
        {"ini": 0.0, "fim": 2.0, "texto": "Bom dia a todos.", "idioma": "pt"},
        {"ini": 2.5, "fim": 4.0, "texto": "Good morning.", "idioma": "en"},
        {"ini": 4.5, "fim": 6.0, "texto": "Chegamos cedo hoje.", "idioma": "pt"},
        {"ini": 6.5, "fim": 8.0, "texto": "Deus in adiutorium.", "idioma": "la"},
    ]
    marcos = []
    saida = traduzir.traduzir_itens(
        itens, "en", caminho,
        progress=lambda e, a, t: marcos.append((a, t)),
        log=lambda m: print("    " + m))

    checa("mesma quantidade de itens", len(saida) == len(itens))
    checa("tempos preservados",
          all(a["ini"] == b["ini"] and a["fim"] == b["fim"]
              for a, b in zip(itens, saida)))
    checa("ordem preservada", all(s is not None for s in saida))

    pt_itens = [s for s in saida if s["idioma_origem"] == "pt"]
    checa("portugues foi traduzido", all(s["traduzido"] for s in pt_itens))

    en_item = next(s for s in saida if s["idioma_origem"] == "en")
    checa("ingles nao foi retraduzido", en_item["traduzido"] is False)
    checa("ingles manteve o texto original",
          en_item["texto"] == "Good morning.")

    la_item = next(s for s in saida if s["idioma_origem"] == "la")
    checa("latim marcado como indisponivel",
          la_item.get("traducao_indisponivel") is True)
    checa("latim manteve o texto original",
          la_item["texto"] == "Deus in adiutorium.")

    checa("progresso chegou ao total", marcos and marcos[-1][0] == len(itens),
          f"ultimo={marcos[-1] if marcos else None}")

    for s in saida:
        print(f"    [{s['idioma_origem']}->{s['idioma']}] "
              f"trad={s['traduzido']}  {s['texto']!r}")

    print("\n" + "=" * 62)
    if falhas:
        print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
        return 1
    print("todos os testes passaram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
