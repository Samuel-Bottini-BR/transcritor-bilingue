# -*- coding: utf-8 -*-
"""Testes da formatacao de legenda. Logica pura: nao usa modelo nem GPU."""

import legendar

falhas = []


def checa(nome, cond, detalhe=""):
    if not cond:
        falhas.append(nome)
    print(f"[{'OK ' if cond else 'FALHOU'}] {nome}" + (f"  {detalhe}" if detalhe else ""))


def main():
    print("=== 1. quebra em duas linhas ===")
    curto = "Frase curta."
    checa("texto curto fica numa linha so",
          legendar.quebrar_linhas(curto) == [curto])

    t = ("O barco sai amanha de manha e voce precisa estar no porto "
         "antes do amanhecer.")
    ls = legendar.quebrar_linhas(t)
    checa("gera no maximo 2 linhas", len(ls) <= 2, f"{len(ls)}")
    checa("nenhuma linha passa de 42", all(len(l) <= 42 for l in ls),
          str([len(l) for l in ls]))
    checa("nao perde nem inventa palavra",
          " ".join(ls).split() == t.split())
    print(f"    {ls}")

    # a virgula so vence se as DUAS metades couberem em 42; senao o corte
    # gramatical perde para o corte viavel, e esta certo que perca
    t2 = "Ele chegou muito cedo, mas ninguem ainda esperava por ele."
    ls2 = legendar.quebrar_linhas(t2)
    checa("prefere cortar na virgula quando cabe",
          ls2[0].rstrip().endswith(","), str(ls2))

    t2b = "Ele chegou cedo, mas ninguem estava esperando por ele naquela manha."
    ls2b = legendar.quebrar_linhas(t2b)
    checa("ignora a virgula quando o resto nao caberia",
          all(len(l) <= 42 for l in ls2b), str([len(l) for l in ls2b]))

    t3 = "Vamos ate a casa da minha avo depois do almoco de domingo."
    ls3 = legendar.quebrar_linhas(t3)
    checa("nao termina linha em preposicao",
          ls3[0].split()[-1].lower() not in legendar._GRUDAM_NO_SEGUINTE,
          str(ls3))

    print("\n=== 2. divisao de legenda longa ===")
    longa = {"ini": 0.0, "fim": 18.0, "texto": " ".join(["palavra"] * 40)}
    partes = legendar.dividir(longa)
    checa("legenda de 18s vira varias", len(partes) > 1, f"{len(partes)}")
    checa("tempo comeca onde comecava", partes[0]["ini"] == 0.0)
    checa("tempo termina onde terminava", partes[-1]["fim"] == 18.0)
    checa("partes em ordem, sem buraco",
          all(abs(a["fim"] - b["ini"]) < 1e-9 for a, b in zip(partes, partes[1:])))
    checa("nenhuma parte passa de 7s",
          all(p["fim"] - p["ini"] <= legendar.MAX_DUR + 0.01 for p in partes),
          str([round(p["fim"] - p["ini"], 1) for p in partes]))
    checa("texto preservado inteiro",
          " ".join(p["texto"] for p in partes).split() == longa["texto"].split())

    curta = {"ini": 0.0, "fim": 2.0, "texto": "Nao precisa dividir."}
    checa("legenda que cabe nao e dividida",
          len(legendar.dividir(curta)) == 1)

    print("\n=== 3. folga entre legendas ===")
    grudadas = [{"ini": 0.0, "fim": 2.0, "texto": "um"},
                {"ini": 2.0, "fim": 4.0, "texto": "dois"},
                {"ini": 4.0, "fim": 6.0, "texto": "tres"}]
    f = legendar.folgar(grudadas)
    checa("cria folga entre todas",
          all(b["ini"] - a["fim"] >= legendar.MIN_GAP - 1e-9
              for a, b in zip(f, f[1:])),
          str([round(b["ini"] - a["fim"], 3) for a, b in zip(f, f[1:])]))
    checa("nao atrasa o inicio (sincronia com a fala)",
          [x["ini"] for x in f] == [0.0, 2.0, 4.0])

    sobreposta = [{"ini": 0.0, "fim": 5.0, "texto": "um"},
                  {"ini": 3.0, "fim": 6.0, "texto": "dois"}]
    f2 = legendar.folgar(sobreposta)
    checa("desfaz sobreposicao", f2[1]["ini"] - f2[0]["fim"] >= legendar.MIN_GAP - 1e-9)

    print("\n=== 4. pipeline completo ===")
    entrada = [
        {"ini": 0.0, "fim": 18.0, "idioma": "pt",
         "texto": ("Este e um trecho bem longo que precisa ser dividido em "
                   "varias legendas porque nao cabe de jeito nenhum numa tela "
                   "so e ainda por cima fica tempo demais parado ali.")},
        {"ini": 18.0, "fim": 19.2, "idioma": "pt", "texto": "Curto."},
        {"ini": 19.2, "fim": 24.0, "idioma": "pt",
         "texto": "Uma frase de tamanho medio, que cabe em duas linhas certas."},
        {"ini": 24.0, "fim": 25.0, "idioma": "pt", "texto": "   "},
    ]
    antes = legendar.medir([
        dict(i, texto=i["texto"]) for i in entrada if i["texto"].strip()])
    saida = legendar.formatar(entrada)
    depois = legendar.medir(saida)

    checa("descarta item vazio",
          all(x["texto"].strip() for x in saida))
    checa("zerou linha longa", depois["linha_longa"] == 0,
          f"antes {antes['linha_longa']} -> depois {depois['linha_longa']}")
    checa("zerou mais de 2 linhas", depois["muitas_linhas"] == 0)
    checa("zerou duracao acima de 7s", depois["duracao_longa"] == 0,
          f"antes {antes['duracao_longa']} -> depois {depois['duracao_longa']}")
    checa("zerou sobreposicao", depois["sobrepostas"] == 0)
    checa("zerou falta de folga", depois["sem_folga"] == 0,
          f"antes {antes['sem_folga']} -> depois {depois['sem_folga']}")
    checa("preserva o campo idioma",
          all(x.get("idioma") == "pt" for x in saida))

    todo_texto_antes = " ".join(i["texto"] for i in entrada).split()
    todo_texto_depois = " ".join(
        x["texto"].replace("\n", " ") for x in saida).split()
    checa("nenhuma palavra perdida no caminho",
          todo_texto_antes == todo_texto_depois,
          f"{len(todo_texto_antes)} -> {len(todo_texto_depois)}")

    print(f"\n    {antes['n']} legendas -> {depois['n']}")
    for x in saida[:4]:
        print(f"    [{x['ini']:5.1f}-{x['fim']:5.1f}] "
              + " | ".join(x["texto"].split("\n")))

    print("\n=== 5. casos de borda ===")
    checa("lista vazia", legendar.formatar([]) == [])
    checa("uma palavra gigante nao trava",
          len(legendar.quebrar_linhas("x" * 100)) >= 1)
    um = legendar.formatar([{"ini": 0.0, "fim": 1.0, "texto": "Oi."}])
    checa("item unico sobrevive", len(um) == 1 and um[0]["texto"] == "Oi.")
    checa("duracao minima aplicada",
          um[0]["fim"] - um[0]["ini"] >= legendar.MIN_DUR - 1e-9,
          f"{um[0]['fim'] - um[0]['ini']:.3f}s")

    print("\n" + "=" * 62)
    if falhas:
        print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
        return 1
    print("todos os testes de formatacao passaram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
