# -*- coding: utf-8 -*-
"""Valida a deteccao de idioma por trecho contra o ground truth do audio
sintetico, e roda o pipeline completo para inspecionar o SRT."""

import motor

MODELO = "small"   # suficiente para validar lang-id; produto usa large-v3
IDIOMAS = ["en", "it"]


def carregar_verdade():
    v = []
    with open("teste_bilingue_verdade.txt", encoding="utf-8") as f:
        for linha in f:
            ini, fim, lang = linha.split()
            v.append((float(ini), float(fim), lang))
    return v


def idioma_verdade(mid, verdade):
    for ini, fim, lang in verdade:
        if ini <= mid <= fim:
            return lang
    return "?"


def main():
    verdade = carregar_verdade()
    modelo, dev, ct = motor.carregar_modelo(MODELO, "cpu", None, "modelos",
                                             log=print)
    audio = motor.decode_audio("teste_bilingue.wav", sampling_rate=motor.SR)
    blocos_t = motor.agrupar(motor.fatiar(audio))

    print(f"\n{len(blocos_t)} blocos detectados pelo VAD\n")
    print(f"{'bloco':>18}  {'detectado':>9}  {'conf':>5}  {'verdade':>7}  ok")
    acertos = 0
    for ini, fim in blocos_t:
        lg, conf = motor.idioma_do_trecho(modelo, audio, ini, fim, IDIOMAS)
        mid = (ini + fim) / 2
        verd = idioma_verdade(mid, verdade)
        ok = (lg == verd)
        acertos += ok
        print(f"  {ini:6.2f}->{fim:6.2f}  {str(lg):>9}  {conf:5.2f}  "
              f"{verd:>7}  {'OK' if ok else 'X'}")
    print(f"\nlang-id: {acertos}/{len(blocos_t)} blocos corretos")

    # pipeline completo -> SRT marcado
    aceitos, descartados, info = motor.transcrever(
        "teste_bilingue.wav", IDIOMAS, MODELO, "cpu", None, "modelos",
        log=lambda m: None)
    motor.escrever_srt(aceitos, "teste_bilingue.srt", marcar=True)
    print(f"\ninfo: {info}")
    print("\n--- teste_bilingue.srt ---")
    with open("teste_bilingue.srt", encoding="utf-8") as f:
        print(f.read())
    if descartados:
        print("descartados:")
        for d in descartados:
            print(f"  {d['ini']:.1f}s [{d['descartado_por']}] {d['texto'][:40]}")


if __name__ == "__main__":
    main()
