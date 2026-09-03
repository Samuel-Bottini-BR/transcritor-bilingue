# -*- coding: utf-8 -*-
"""Gera um audio sintetico alternando ingles e italiano (code-switching) com
edge-tts, para validar a deteccao de idioma por trecho.

Escreve teste_bilingue.wav (16 kHz mono) e imprime a linha do tempo com o
idioma verdadeiro de cada trecho (ground truth) para comparar com a saida do
motor.
"""

import asyncio
import os
import tempfile

import numpy as np
import soundfile as sf
import edge_tts

from faster_whisper.audio import decode_audio

SR = 16000

# Alterna en/it varias vezes, imitando o filme (personagem fala ingles, os
# outros respondem em italiano).
ROTEIRO = [
    ("en", "en-US-AriaNeural",  "Good evening. I did not expect to find you here tonight."),
    ("it", "it-IT-ElsaNeural",  "Buonasera signora. Che sorpresa vederla di nuovo in questo posto."),
    ("en", "en-US-GuyNeural",   "The boat leaves at dawn. We should be ready before the sun rises."),
    ("it", "it-IT-DiegoNeural", "Il mare stanotte e calmo, ma domani potrebbe cambiare tutto."),
    ("en", "en-US-AriaNeural",  "I have waited for this moment far longer than you can imagine."),
    ("it", "it-IT-ElsaNeural",  "Non ho mai visto un tramonto cosi bello in tutta la mia vita."),
    ("en", "en-US-GuyNeural",   "Tell me the truth, once and for all, before it is too late."),
    ("it", "it-IT-DiegoNeural", "Ti prometto che ritornero prima della fine dell'estate, amore mio."),
]

SILENCIO_S = 0.8  # silencio entre falas, forca o VAD a cortar entre trechos


async def _sintetizar(texto, voz, destino_mp3):
    com = edge_tts.Communicate(texto, voz)
    await com.save(destino_mp3)


def main():
    tmp = tempfile.mkdtemp(prefix="tts_")
    pedacos = []
    verdade = []  # (ini_s, fim_s, idioma)
    t = 0.0
    silencio = np.zeros(int(SILENCIO_S * SR), dtype=np.float32)

    for i, (lang, voz, texto) in enumerate(ROTEIRO):
        mp3 = os.path.join(tmp, f"{i}.mp3")
        asyncio.run(_sintetizar(texto, voz, mp3))
        sinal = decode_audio(mp3, sampling_rate=SR)
        dur = len(sinal) / SR
        verdade.append((round(t, 2), round(t + dur, 2), lang))
        pedacos.append(sinal)
        pedacos.append(silencio)
        t += dur + SILENCIO_S
        print(f"  [{lang}] {dur:5.1f}s  {texto[:50]}...")

    audio = np.concatenate(pedacos)
    sf.write("teste_bilingue.wav", audio, SR)
    print(f"\nteste_bilingue.wav  ({len(audio)/SR:.1f}s)")

    with open("teste_bilingue_verdade.txt", "w", encoding="utf-8") as f:
        for ini, fim, lang in verdade:
            f.write(f"{ini:7.2f}  {fim:7.2f}  {lang}\n")
    print("Ground truth:")
    for ini, fim, lang in verdade:
        print(f"  {ini:7.2f} -> {fim:7.2f}  {lang}")


if __name__ == "__main__":
    main()
