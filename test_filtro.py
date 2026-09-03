# -*- coding: utf-8 -*-
"""Testa o filtro de alucinacao com entradas fabricadas que reproduzem os
quatro erros reais observados na transcricao do filme."""

from motor import marcar_repeticoes, parece_alucinacao

CASOS = [
    # (nome, texto, logprob, no_speech, motivo_esperado)
    # Erro 1: loop de repeticao em cima de canto religioso
    ("loop_salamat",
     "Salamat Salamat Salamat Salamat Salamat Salamat Salamat Salamat",
     -0.3, 0.1, "repeticao em loop"),
    ("loop_lalala",
     "lalala lalala lalala lalala lalala",
     -0.4, 0.1, "repeticao em loop"),

    # Erro 2: idioma inventado (tamil/coreano/devanagari) num trecho que
    # deveria ser en/it. Backstop caso a lang-id de conjunto fechado falhe.
    ("alfabeto_tamil",
     "தமிழ் மொழி",
     -0.5, 0.1, "alfabeto inesperado"),
    ("alfabeto_devanagari",
     "नमस्ते दुनिया",
     -0.5, 0.1, "alfabeto inesperado"),
    ("alfabeto_coreano",
     "안녕하세요 세계",
     -0.5, 0.1, "alfabeto inesperado"),

    # Erro 3: legenda gerada onde nao ha fala (erupcao, mar, trilha)
    ("sem_fala",
     "the wind blows softly",
     -0.4, 0.85, "provavelmente sem fala"),

    # Confianca baixissima (log-prob no chao) tambem cai
    ("confianca_baixa",
     "mumble something unclear",
     -1.6, 0.2, "confianca baixa"),

    ("vazio", "   ", -0.3, 0.1, "vazio"),

    # Erro 4 (o oposto do descarte): fala VALIDA nao pode ser jogada fora.
    # Aqui garantimos que os trechos legitimos passam (motivo == None), senao o
    # filtro estaria "perdendo falas" por conta propria.
    ("valido_en",
     "Where have you been all this time?",
     -0.25, 0.05, None),
    ("valido_it",
     "Non ho mai visto un posto cosi bello in vita mia.",
     -0.30, 0.08, None),
    # Repeticao legitima curta NAO pode ser confundida com loop
    ("valido_repeticao_curta",
     "No, no, no!",
     -0.30, 0.10, None),
]


# Repeticao ENTRE segmentos irmaos do mesmo bloco. O filtro de texto acima nao
# enxerga isso: cada segmento, sozinho, e uma frase curta e normal. Medido no
# Stromboli (1950): 29 segmentos identicos num unico bloco de 24 segundos.
CASOS_REPETICAO = [
    # (nome, textos_do_bloco, descartes_esperados)
    ("loop_no_bloco",
     ["Thank you."] * 29,
     [False] + [True] * 28),

    # pontuacao e caixa nao devem esconder a repeticao
    ("loop_variando_pontuacao",
     ["Thank you.", "thank you", "Thank you!"],
     [False, True, True]),

    # bloco normal: nenhum segmento se repete
    ("dialogo_normal",
     ["Where have you been?", "I was at the harbour.", "For how long?"],
     [False, False, False]),

    # uma repeticao isolada e comum em dialogo real e deve passar quando o
    # limite permite; com MAX=1 a segunda ja cai. Fixamos o comportamento.
    ("repeticao_dupla",
     ["Si.", "No.", "Si."],
     [False, False, True]),

    # texto vazio nao conta como repeticao (quem trata isso e parece_alucinacao)
    ("vazios_nao_contam",
     ["  ", "...", "  "],
     [False, False, False]),
]


def main():
    ok = 0
    for nome, texto, lp, ns, esperado in CASOS:
        got = parece_alucinacao(texto, lp, ns)
        status = "OK " if got == esperado else "FALHOU"
        if got == esperado:
            ok += 1
        print(f"[{status}] {nome:24s} esperado={esperado!r:26s} obtido={got!r}")

    print()
    for nome, textos, esperado in CASOS_REPETICAO:
        got = marcar_repeticoes(textos)
        status = "OK " if got == esperado else "FALHOU"
        if got == esperado:
            ok += 1
        print(f"[{status}] {nome:24s} {sum(got)} de {len(textos)} descartados")

    total = len(CASOS) + len(CASOS_REPETICAO)
    print(f"\n{ok}/{total} casos passaram")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
