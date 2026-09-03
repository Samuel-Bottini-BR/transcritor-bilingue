# -*- coding: utf-8 -*-
"""Benchmark: quanto custa cada bloco no large-v3 com diferentes precisoes,
na GPU de 4 GB. Mede lang-id + transcricao em blocos reais do filme."""
import time, gc
import cuda_setup  # noqa
import motor
import download_modelo as dm

FILME = r"C:\Users\fotog\Desktop\Stromboli (1950).ia.mp4"
BASE = r"C:\Users\fotog\transcritor-bilingue\dist\TranscritorBilingue\modelos"
N = 12  # blocos para amostrar

print("decodificando audio do filme (uma vez)...", flush=True)
t = time.time()
audio = motor.decode_audio(FILME, sampling_rate=motor.SR)
dur_total = len(audio) / motor.SR
print(f"  {dur_total/60:.1f} min em {time.time()-t:.0f}s", flush=True)

blocos = motor.agrupar(motor.fatiar(audio))
print(f"  {len(blocos)} blocos; amostrando {N}", flush=True)
amostra = blocos[:N]
dur_amostra = sum(f - i for i, f in amostra)

modelo_path = dm.baixar_modelo("large-v3", BASE)  # ja em cache


def mede(ct):
    gc.collect()
    t0 = time.time()
    m, dev, ctr = motor.carregar_modelo(modelo_path, "cuda", ct, log=lambda s: None)
    t_load = time.time() - t0
    t1 = time.time()
    for ini, fim in amostra:
        lg, conf = motor.idioma_do_trecho(m, audio, ini, fim, ["en", "it"])
        corte = audio[int(ini*motor.SR):int(fim*motor.SR)]
        segs, _ = m.transcribe(corte, language=lg or "it", beam_size=5,
                               condition_on_previous_text=False,
                               temperature=[0.0, 0.2])
        list(segs)
    t_proc = time.time() - t1
    del m
    gc.collect()
    por_bloco = t_proc / N
    proj_min = por_bloco * len(blocos) / 60
    print(f"  {ct:14s} load={t_load:4.1f}s  {por_bloco:5.2f}s/bloco  "
          f"({dur_amostra:.0f}s audio em {t_proc:.0f}s)  "
          f"=> filme ~{proj_min:.0f} min", flush=True)


for ct in ["float16", "int8_float16", "int8"]:
    try:
        mede(ct)
    except Exception as e:
        print(f"  {ct}: FALHOU {type(e).__name__}: {str(e)[:100]}", flush=True)
