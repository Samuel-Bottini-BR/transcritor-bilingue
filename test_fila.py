# -*- coding: utf-8 -*-
"""Testes da fila: nomes de arquivo, previsao de saida e organizacao de pastas.

Tudo aqui e logica pura - nao baixa, nao transcreve, nao abre janela.
"""

import os
import tempfile

import fila

falhas = []


def checa(nome, cond, detalhe=""):
    if not cond:
        falhas.append(nome)
    print(f"[{'OK ' if cond else 'FALHOU'}] {nome}" + (f"  {detalhe}" if detalhe else ""))


def main():
    print("=== 1. nomes de arquivo seguros no Windows ===")
    checa("tira caracteres proibidos",
          fila._nome_seguro('a/b:c*d?e"f<g>h|i') == "a-b-c-d-e-f-g-h-i",
          fila._nome_seguro('a/b:c*d?e"f<g>h|i'))
    checa("nome vazio vira placeholder", fila._nome_seguro("   ") == "sem-nome")
    checa("ponto final removido (Windows nao aceita)",
          not fila._nome_seguro("nome.").endswith("."))
    checa("corta nome gigante", len(fila._nome_seguro("x" * 400)) <= 110)
    checa("preserva acentos",
          fila._nome_seguro("Vésperas do Breviário") == "Vésperas do Breviário")

    print("\n=== 2. nome base ===")
    t = fila.Trabalho(origem="http://x", titulo="Como Rezar as Vésperas")
    checa("sem indice usa o titulo", t.nome_base() == "Como Rezar as Vésperas")
    t.indice = 6
    checa("com indice numera com dois digitos",
          t.nome_base() == "06 - Como Rezar as Vésperas", t.nome_base())
    t.nome_saida = "meu nome"
    checa("nome manual tem precedencia", t.nome_base() == "meu nome")

    arq = fila.Trabalho(origem=r"D:\Filmes\Stromboli (1950).mkv", e_url=False,
                        titulo="Stromboli (1950)")
    checa("arquivo local usa o nome do arquivo",
          arq.nome_base() == "Stromboli (1950)")

    print("\n=== 3. previsao de arquivos ===")
    cfg = fila.Config(pasta_midia=r"D:\midia", pasta_legendas=r"D:\legendas",
                      pasta_modelos=r"D:\modelos")
    t = fila.Trabalho(origem="http://x", titulo="Video", e_url=True,
                      idiomas=["pt"], formatos=["srt"], relatorio=True)
    prev = t.arquivos_previstos(cfg)
    tipos = [k for _, k in prev]
    checa("audio + legenda + relatorio", tipos == ["audio", "legenda", "relatorio"],
          str(tipos))
    checa("audio vai para a pasta de midia",
          prev[0][0] == os.path.join(r"D:\midia", "Video.m4a"), prev[0][0])
    checa("legenda vai para a pasta de legendas",
          prev[1][0] == os.path.join(r"D:\legendas", "Video.srt"), prev[1][0])

    t.baixar_video = True
    checa("video muda a extensao para mp4",
          t.arquivos_previstos(cfg)[0][0].endswith(".mp4"))

    t.formatos = ["srt", "vtt", "txt"]
    t.traduzir_ligado = True
    t.traduzir_para = ["en"]
    prev = t.arquivos_previstos(cfg)
    nomes = [os.path.basename(p) for p, _ in prev]
    checa("3 formatos + 3 traduzidos + relatorio + midia",
          len(prev) == 8, f"{len(prev)}: {nomes}")
    checa("traducao ganha sufixo de idioma", "Video.en.srt" in nomes, str(nomes))
    checa("original nao ganha sufixo", "Video.srt" in nomes)

    t.transcrever_ligado = False
    checa("sem transcrever, so a midia",
          len(t.arquivos_previstos(cfg)) == 1)

    print("\n=== 4. organizacao das pastas ===")
    t = fila.Trabalho(origem="http://x", titulo="V", e_url=True,
                      playlist="Breviarium Romanum")
    cfg.organizacao = fila.JUNTO
    checa("junto: tudo na raiz",
          cfg.destino_legenda(t) == r"D:\legendas")
    cfg.organizacao = fila.POR_PLAYLIST
    checa("por playlist: subpasta com o nome do grupo",
          cfg.destino_legenda(t) == os.path.join(r"D:\legendas",
                                                 "Breviarium Romanum"),
          cfg.destino_legenda(t))
    checa("por playlist tambem separa a midia",
          t.pasta_midia_efetiva(cfg) == os.path.join(r"D:\midia",
                                                     "Breviarium Romanum"))
    t2 = fila.Trabalho(origem="http://y", titulo="Solto", e_url=True)
    checa("por playlist, item solto fica na raiz",
          cfg.destino_legenda(t2) == r"D:\legendas")

    cfg.organizacao = fila.AO_LADO
    t.caminho_midia = r"D:\outra\pasta\V.m4a"
    checa("ao lado: usa a pasta da midia",
          cfg.destino_legenda(t) == r"D:\outra\pasta", cfg.destino_legenda(t))

    print("\n=== 5. montagem a partir de arquivos ===")
    padrao = fila.Trabalho(origem="", idiomas=["pt", "en"], modelo="small",
                           formatos=["srt", "txt"], traduzir_para=["en"])
    with tempfile.TemporaryDirectory() as d:
        f1 = os.path.join(d, "um.mp4")
        open(f1, "wb").close()
        ts = fila.de_arquivos([f1], padrao)
        checa("um trabalho por arquivo", len(ts) == 1)
        checa("arquivo local desliga o download", ts[0].baixar_ligado is False)
        checa("herda idiomas do padrao", ts[0].idiomas == ["pt", "en"])
        checa("herda formatos do padrao", ts[0].formatos == ["srt", "txt"])
        checa("nao compartilha a lista (copia)",
              ts[0].idiomas is not padrao.idiomas)
        checa("comeca em espera", ts[0].estado == fila.ESPERA)

    print("\n=== 6. executor: erros esperados ===")
    cfg2 = fila.Config(pasta_midia=".", pasta_legendas=".", pasta_modelos=".")
    ex = fila.Executor(cfg2)

    sumido = fila.Trabalho(origem=r"Z:\nao\existe.mp4", e_url=False,
                           baixar_ligado=False)
    ex.rodar([sumido])
    checa("arquivo inexistente vira erro", sumido.estado == fila.ERRO,
          sumido.erro[:44])

    sem_fonte = fila.Trabalho(origem="http://x", e_url=True,
                              baixar_ligado=False)
    ex2 = fila.Executor(cfg2)
    ex2.rodar([sem_fonte])
    checa("url com download desligado vira erro",
          sem_fonte.estado == fila.ERRO, sem_fonte.erro[:44])

    ex3 = fila.Executor(cfg2)
    ex3.cancelar()
    t3 = fila.Trabalho(origem="x", e_url=False, baixar_ligado=False)
    ex3.rodar([t3])
    checa("cancelado antes de comecar nao roda", t3.estado == fila.ESPERA)

    print("\n" + "=" * 62)
    if falhas:
        print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
        return 1
    print("todos os testes da fila passaram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
