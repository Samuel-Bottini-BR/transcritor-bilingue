#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fila de trabalhos: a esteira baixar -> transcrever -> traduzir.

Este modulo nao conhece Qt. A interface so observa: passa callbacks e recebe
eventos. Isso permite testar a logica de fila, dependencias entre etapas e
nomes de arquivo sem abrir janela nenhuma.

Por que a fila e SEQUENCIAL: dois modelos grandes nao cabem juntos em 4 GB de
VRAM, e rodar dois em paralelo na mesma GPU fica mais lento que em sequencia.
Do ponto de vista do usuario e igual - ele larga dez videos e volta depois.
"""

from __future__ import annotations

import os
import threading
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

import baixar
import download_modelo
import legendar
import motor
import traduzir

# estados de um trabalho
ESPERA, RODANDO, PRONTO, ERRO, CANCELADO = (
    "espera", "rodando", "pronto", "erro", "cancelado")

# nomes de etapa que a interface mostra
ETAPAS = {
    "baixando": "Baixando",
    "decodificando": "Decodificando o audio",
    "detectando fala": "Detectando trechos de fala",
    "identificando idioma": "Identificando o idioma",
    "transcrevendo": "Transcrevendo",
    "traduzindo": "Traduzindo",
    "baixando modelo": "Baixando o modelo",
}


class CanceladoError(Exception):
    pass


def _noop(*_a, **_k):
    pass


# --------------------------------------------------------------------------
# Configuracao de pastas
# --------------------------------------------------------------------------

# como organizar a saida
JUNTO, POR_PLAYLIST, AO_LADO = "junto", "por_playlist", "ao_lado"


@dataclass
class Config:
    """Onde tudo e gravado. E o que o botao 'Pastas...' edita."""
    pasta_midia: str = ""       # videos/audios baixados
    pasta_legendas: str = ""    # .srt, .vtt, .txt, relatorio
    pasta_modelos: str = ""     # pesos do Whisper e do NLLB
    organizacao: str = JUNTO
    guardar_midia: bool = True  # apagar o baixado depois de transcrever?

    def destino_legenda(self, t: "Trabalho") -> str:
        """Pasta final da legenda deste trabalho."""
        if self.organizacao == AO_LADO and t.caminho_midia:
            return os.path.dirname(os.path.abspath(t.caminho_midia))
        if self.organizacao == POR_PLAYLIST and t.playlist:
            return os.path.join(self.pasta_legendas, _nome_seguro(t.playlist))
        return self.pasta_legendas


_PROIBIDOS = '<>:"/\\|?*'


def _nome_seguro(nome: str, limite: int = 110) -> str:
    """Nome de arquivo valido no Windows, sem perder legibilidade."""
    limpo = "".join(("-" if c in _PROIBIDOS else c) for c in nome)
    limpo = "".join(c for c in limpo if ord(c) >= 32).strip(" .")
    return (limpo[:limite].strip() or "sem-nome")


# --------------------------------------------------------------------------
# Trabalho
# --------------------------------------------------------------------------

@dataclass
class Trabalho:
    origem: str                       # url ou caminho no disco
    titulo: str = ""
    duracao_s: float = 0.0
    e_url: bool = False
    playlist: Optional[str] = None    # nome do grupo, se veio de uma playlist
    indice: Optional[int] = None      # posicao dentro da playlist

    # --- etapas (as tres da esteira) ---
    baixar_ligado: bool = True
    baixar_video: bool = False        # False = so o audio
    transcrever_ligado: bool = True
    idiomas: list = field(default_factory=lambda: ["en", "it"])
    modelo: str = "large-v3"
    traduzir_ligado: bool = False
    traduzir_para: list = field(default_factory=list)

    # --- saida ---
    formatos: list = field(default_factory=lambda: ["srt"])
    relatorio: bool = True
    marcar_idioma: bool = False
    nome_saida: str = ""              # sem extensao; vazio = derivado do titulo

    # --- estado ---
    estado: str = ESPERA
    etapa: str = ""
    atual: int = 0
    total: int = 0
    erro: str = ""
    caminho_midia: Optional[str] = None
    saidas: list = field(default_factory=list)
    resumo: dict = field(default_factory=dict)

    def nome_base(self) -> str:
        if self.nome_saida:
            return _nome_seguro(self.nome_saida)
        base = self.titulo or os.path.splitext(os.path.basename(self.origem))[0]
        if self.indice:
            base = f"{self.indice:02d} - {base}"
        return _nome_seguro(base)

    def arquivos_previstos(self, cfg: "Config") -> list:
        """Os arquivos que ESTE trabalho vai gerar, com o caminho completo.

        A interface mostra isso antes de rodar: o usuario ve o nome exato dos
        arquivos antes de eles existirem.
        """
        fora = []
        base = self.nome_base()
        if self.baixar_ligado and self.e_url:
            ext = "mp4" if self.baixar_video else "m4a"
            fora.append((os.path.join(self.pasta_midia_efetiva(cfg),
                                      f"{base}.{ext}"),
                         "video" if self.baixar_video else "audio"))
        if not self.transcrever_ligado:
            return fora
        pasta = cfg.destino_legenda(self)
        for f in self.formatos:
            fora.append((os.path.join(pasta, f"{base}.{f}"), "legenda"))
        for alvo in (self.traduzir_para if self.traduzir_ligado else []):
            for f in self.formatos:
                fora.append((os.path.join(pasta, f"{base}.{alvo}.{f}"),
                             "traducao"))
        if self.relatorio:
            fora.append((os.path.join(pasta, f"{base}_relatorio.json"),
                         "relatorio"))
        return fora

    def pasta_midia_efetiva(self, cfg: "Config") -> str:
        if cfg.organizacao == POR_PLAYLIST and self.playlist:
            return os.path.join(cfg.pasta_midia, _nome_seguro(self.playlist))
        return cfg.pasta_midia


# --------------------------------------------------------------------------
# Execucao
# --------------------------------------------------------------------------

class Executor:
    """Roda os trabalhos um a um.

    eventos:
      ao_mudar(trabalho)  - estado/progresso mudou
      ao_log(str)         - mensagem solta
    """

    def __init__(self, cfg: Config,
                 ao_mudar: Callable = _noop,
                 ao_log: Callable = _noop):
        self.cfg = cfg
        self.ao_mudar = ao_mudar
        self.ao_log = ao_log
        self.cancel = threading.Event()
        self._atual: Optional[Trabalho] = None

    def cancelar(self):
        self.cancel.set()

    def rodar(self, trabalhos: list):
        """Processa a lista inteira. Bloqueia - chame numa thread."""
        for t in trabalhos:
            if self.cancel.is_set():
                break
            if t.estado not in (ESPERA, ERRO):
                continue
            self._atual = t
            try:
                self._um(t)
                t.estado = PRONTO
                t.etapa = ""
            except (CanceladoError, motor.CanceladoError,
                    baixar.CanceladoError, traduzir.CanceladoError,
                    download_modelo.CanceladoError):
                t.estado = CANCELADO
                t.etapa = ""
            except (baixar.BaixarError, ConnectionError, ValueError) as e:
                # erros esperados: mensagem limpa, sem traceback
                t.estado, t.erro, t.etapa = ERRO, str(e), ""
            except Exception as e:
                t.estado = ERRO
                t.erro = f"{e}"
                self.ao_log(traceback.format_exc())
                t.etapa = ""
            self.ao_mudar(t)
        self._atual = None

    # -- uma passagem completa por um trabalho --------------------------

    def _um(self, t: Trabalho):
        t.estado, t.erro, t.saidas = RODANDO, "", []
        self._marca(t, "", 0, 0)

        # ---- etapa 1: baixar ----
        caminho = t.origem
        if t.e_url and t.baixar_ligado:
            pasta = t.pasta_midia_efetiva(self.cfg)
            self.ao_log(f"baixando {t.titulo}...")
            caminho = baixar.baixar(
                t.origem, pasta, so_audio=not t.baixar_video,
                nome=t.nome_base(),
                progress=lambda e, a, tt: self._marca(t, e, a, tt),
                cancel=self.cancel, log=self.ao_log)
            t.caminho_midia = caminho
            t.saidas.append(caminho)
        elif not t.e_url:
            t.caminho_midia = caminho
            if not os.path.isfile(caminho):
                raise ValueError(f"arquivo nao encontrado: {caminho}")
        else:
            raise ValueError(
                "sem download e sem arquivo local: nao ha o que transcrever")

        if not t.transcrever_ligado:
            return

        # ---- etapa 2: transcrever ----
        self._marca(t, "baixando modelo", 0, 0)
        caminho_modelo = download_modelo.baixar_modelo(
            t.modelo, self.cfg.pasta_modelos,
            progress=lambda a, tt: self._marca(t, "baixando modelo", a, tt),
            cancel=self.cancel)

        # modelo leve so para a identificacao de idioma (poupa um encode caro
        # por bloco no modelo grande)
        modelo_idioma = None
        if t.modelo != "small":
            modelo_idioma = download_modelo.baixar_modelo(
                "small", self.cfg.pasta_modelos, cancel=self.cancel)

        aceitos, descartados, info = motor.transcrever(
            caminho, t.idiomas,
            nome_modelo=caminho_modelo, device="auto",
            modelo_idioma=modelo_idioma,
            progress=lambda e, a, tt: self._marca(t, e, a, tt),
            cancel=self.cancel, log=self.ao_log)

        pasta_leg = self.cfg.destino_legenda(t)
        os.makedirs(pasta_leg, exist_ok=True)
        base = os.path.join(pasta_leg, t.nome_base())
        self._gravar(t, aceitos, base, "")

        if t.relatorio:
            rel = base + "_relatorio.json"
            motor.escrever_relatorio(aceitos, descartados, info, rel)
            t.saidas.append(rel)

        t.resumo = {"aceitos": len(aceitos), "descartados": len(descartados),
                    "device": info.get("device"), "modelo": t.modelo}

        # ---- etapa 3: traduzir ----
        if t.traduzir_ligado and t.traduzir_para and aceitos:
            self._marca(t, "baixando modelo", 0, 0)
            modelo_trad = download_modelo.baixar_modelo(
                "nllb-600m", self.cfg.pasta_modelos,
                progress=lambda a, tt: self._marca(t, "baixando modelo", a, tt),
                cancel=self.cancel)
            for alvo in t.traduzir_para:
                traduzidos = traduzir.traduzir_itens(
                    aceitos, alvo, modelo_trad, device="auto",
                    progress=lambda e, a, tt: self._marca(t, e, a, tt),
                    cancel=self.cancel, log=self.ao_log)
                self._gravar(t, traduzidos, base, f".{alvo}")

        # ---- limpeza opcional da midia baixada ----
        if (t.e_url and t.baixar_ligado and not self.cfg.guardar_midia
                and t.caminho_midia and os.path.isfile(t.caminho_midia)):
            try:
                os.remove(t.caminho_midia)
                t.saidas = [s for s in t.saidas if s != t.caminho_midia]
                t.caminho_midia = None
            except OSError as e:
                self.ao_log(f"nao consegui apagar a midia: {e}")

    def _gravar(self, t: Trabalho, itens: list, base: str, sufixo: str):
        # SRT e VTT sao legenda de tela: passam pela formatacao (divisao,
        # quebra em duas linhas, folga). O TXT e texto para ler ou colar, entao
        # recebe as frases inteiras, sem quebras artificiais no meio.
        formatados = legendar.formatar(itens)
        for f in t.formatos:
            destino = f"{base}{sufixo}.{f}"
            if f == "srt":
                motor.escrever_srt(formatados, destino, marcar=t.marcar_idioma)
            elif f == "vtt":
                motor.escrever_vtt(formatados, destino, marcar=t.marcar_idioma)
            elif f == "txt":
                motor.escrever_txt(itens, destino, marcar=t.marcar_idioma)
            else:
                continue
            t.saidas.append(destino)

    def _marca(self, t: Trabalho, etapa, atual, total):
        t.etapa, t.atual, t.total = etapa, atual, total
        self.ao_mudar(t)


# --------------------------------------------------------------------------
# Montagem da fila a partir de um link ou de arquivos
# --------------------------------------------------------------------------

def de_link(url: str, modelo_padrao: "Trabalho",
            cancel: Optional[threading.Event] = None,
            log: Callable = _noop) -> list:
    """Resolve o link e devolve um trabalho por video.

    Uma playlist vira N trabalhos que compartilham o nome do grupo, para a
    interface poder mostra-los recolhidos sob um cabecalho so.
    """
    info = baixar.resolver(url, playlist=True, cancel=cancel, log=log)
    grupo = info["titulo"] if info["playlist"] else None
    saida = []
    for item in info["itens"]:
        t = _copiar_config(modelo_padrao)
        t.origem = item["url"]
        t.titulo = item["titulo"]
        t.duracao_s = item["duracao_s"]
        t.e_url = True
        t.playlist = grupo
        t.indice = item["indice"] if info["playlist"] else None
        saida.append(t)
    return saida


def de_arquivos(caminhos: list, modelo_padrao: "Trabalho") -> list:
    saida = []
    for c in caminhos:
        t = _copiar_config(modelo_padrao)
        t.origem = c
        t.titulo = os.path.splitext(os.path.basename(c))[0]
        t.e_url = False
        t.baixar_ligado = False      # ja esta no disco
        t.duracao_s = _duracao(c)
        saida.append(t)
    return saida


def _copiar_config(m: Trabalho) -> Trabalho:
    """Novo trabalho herdando as escolhas atuais, sem herdar estado."""
    return Trabalho(
        origem="", baixar_ligado=m.baixar_ligado, baixar_video=m.baixar_video,
        transcrever_ligado=m.transcrever_ligado, idiomas=list(m.idiomas),
        modelo=m.modelo, traduzir_ligado=m.traduzir_ligado,
        traduzir_para=list(m.traduzir_para), formatos=list(m.formatos),
        relatorio=m.relatorio, marcar_idioma=m.marcar_idioma)


def _duracao(caminho: str) -> float:
    try:
        import av
        c = av.open(caminho)
        d = (c.duration / 1e6) if c.duration else 0.0
        c.close()
        return d
    except Exception:
        return 0.0
