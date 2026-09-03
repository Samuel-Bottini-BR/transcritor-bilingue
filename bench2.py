# -*- coding: utf-8 -*-
"""Benchmark rapido: separa o custo da identificacao de idioma (encode fixo de
30s por bloco) do custo da transcricao (escala com a duracao). Projeta o tempo
do filme (328 blocos, ~106 min)."""
import time, gc
import cuda_setup  # noqa
import motor
import download_modelo as dm

BASE = r"C:\Users\fotog\transcritor-bilingue\dist\TranscritorBilingue\modelos"
audio = motor.decode_audio(r"C:\Users\fotog\transcritor-bilingue\teste_bilingue.wav",
                           sampling_rate=motor.SR)
blocos = motor.agrupar(motor.fatiar(audio))
N = len(blocos)

# dados reais do filme para projetar
FILME_BLOCOS = 328
FILME_FALA_S = 60 * 60  # estimativa de ~60 min de fala liquida (VAD)


def bench(nome, path):
    m, dev, ct = motor.carregar_modelo(path, "cuda", "float16", log=lambda s: None)
    # aquece
    motor.idioma_do_trecho(m, audio, *blocos[0], ["en", "it"])
    t0 = time.time()
    for ini, fim in blocos:
        motor.idioma_do_trecho(m, audio, ini, fim, ["en", "it"])
    t_lang = (time.time() - t0) / N            # s por bloco (encode de 30s)
    t1 = time.time()
    seg_audio = 0.0
    for ini, fim in blocos:
        corte = audio[int(ini*motor.SR):int(fim*motor.SR)]
        seg_audio += (fim - ini)
        segs, _ = m.transcribe(corte, language="it", beam_size=5,
                               condition_on_previous_text=False,
                               temperature=[0.0, 0.2])
        list(segs)
    t_trans = (time.time() - t1) / seg_audio   # s por segundo de audio
    del m; gc.collect()
    proj = (t_lang * FILME_BLOCOS + t_trans * FILME_FALA_S) / 60
    print(f"{nome:10s}: lang-id {t_lang:.2f}s/bloco | transcricao "
          f"{t_trans:.2f}s por s de audio | FILME ~{proj:.0f} min", flush=True)


bench("small", dm.baixar_modelo("small", BASE))
bench("large-v3", dm.baixar_modelo("large-v3", BASE))
