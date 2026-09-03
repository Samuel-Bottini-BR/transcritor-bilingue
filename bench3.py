# -*- coding: utf-8 -*-
"""Mede a taxa de transcricao (s por s de audio) de medium e large-v3 e projeta
o tempo do filme com a otimizacao de dois passos (pequeno faz o idioma)."""
import time, gc
import cuda_setup  # noqa
import motor
import download_modelo as dm

BASE = r"C:\Users\fotog\transcritor-bilingue\dist\TranscritorBilingue\modelos"
audio = motor.decode_audio(r"C:\Users\fotog\transcritor-bilingue\teste_bilingue.wav",
                           sampling_rate=motor.SR)
blocos = motor.agrupar(motor.fatiar(audio))

FILME_BLOCOS = 328
FILME_FALA_S = 55 * 60      # ~55 min de fala liquida (estimativa)
LANGID_SMALL = 1.32         # s/bloco (medido, GPU limpa)


def taxa_transcricao(path):
    m, _, _ = motor.carregar_modelo(path, "cuda", "float16", log=lambda s: None)
    corte0 = audio[int(blocos[0][0]*motor.SR):int(blocos[0][1]*motor.SR)]
    list(m.transcribe(corte0, language="it", beam_size=5,
                      condition_on_previous_text=False, temperature=0.0)[0])  # aquece
    t = time.time(); sa = 0.0
    for ini, fim in blocos:
        sa += fim - ini
        list(m.transcribe(audio[int(ini*motor.SR):int(fim*motor.SR)],
                          language="it", beam_size=5,
                          condition_on_previous_text=False,
                          temperature=[0.0, 0.2])[0])
    r = (time.time() - t) / sa
    del m; gc.collect()
    return r


for nome in ["medium", "large-v3"]:
    path = dm.baixar_modelo(nome, BASE)
    r = taxa_transcricao(path)
    proj = (LANGID_SMALL * FILME_BLOCOS + r * FILME_FALA_S) / 60
    print(f"{nome:9s}: transcricao {r:.2f}s/s | dois passos => FILME ~{proj:.0f} min",
          flush=True)
