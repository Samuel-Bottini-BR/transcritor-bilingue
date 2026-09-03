#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download de video/audio do YouTube (e dos outros sites que o yt-dlp suporta).

Duas operacoes, deliberadamente separadas:

  resolver(url)  -> le SO os metadados. Um link de playlist vira a lista de
                    itens em segundos, sem baixar nada. E o que permite a
                    interface montar a fila e mostrar duracao e estimativa
                    ANTES de gastar banda.

  baixar(item)   -> baixa de fato um item.

A separacao existe porque o erro mais caro do usuario e baixar 2 GB do video
errado. Resolver primeiro, confirmar, baixar depois.

Sobre formato (importa para o empacotamento):
  - so_audio=True pega uma faixa unica (m4a/webm) e NAO precisa do ffmpeg.
  - so_audio=False tenta primeiro um stream progressivo (video+audio ja no
    mesmo arquivo, tambem sem ffmpeg). So cai para o formato separado
    (que exige merge, e portanto ffmpeg) se o ffmpeg existir.
"""

from __future__ import annotations

import os
import shutil
import threading
from typing import Callable, Optional

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# Mesma assinatura usada por motor.py: cb(etapa, atual, total).
# total <= 0 significa "sem contador" (indeterminado).
ProgressCb = Callable[[str, int, int], None]


class CanceladoError(Exception):
    """Levantada quando o usuario cancela no meio do download."""


class BaixarError(Exception):
    """Falha de rede, video indisponivel, restrito por idade, etc."""


def _noop(*_args, **_kwargs) -> None:
    pass


def _checa_cancelamento(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise CanceladoError()


# --------------------------------------------------------------------------
# Dependencias externas
# --------------------------------------------------------------------------

def ffmpeg_disponivel() -> bool:
    """True se existe um ffmpeg no PATH ou ao lado do executavel.

    Sem ele nao da para juntar video e audio separados; o download de video
    cai para o stream progressivo, que no YouTube costuma parar em 720p.
    """
    if shutil.which("ffmpeg"):
        return True
    aqui = os.path.dirname(os.path.abspath(__file__))
    return os.path.isfile(os.path.join(aqui, "ffmpeg.exe"))


def _opcoes_base(log: Callable[[str], None]) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # o yt-dlp fala pelo logger; sem isso ele escreve direto no stderr e
        # polui o console do app empacotado
        "logger": _Logger(log),
        # nao criar arquivos extras que o usuario nao pediu
        "writethumbnail": False,
        "writeinfojson": False,
    }


class _Logger:
    """Adaptador do logger do yt-dlp para o callback de log do app."""

    def __init__(self, log: Callable[[str], None]):
        self._log = log

    def debug(self, msg):
        # o yt-dlp manda as linhas normais como debug, prefixadas com '[debug] '
        if not msg.startswith("[debug] "):
            self._log(msg)

    def info(self, msg):
        self._log(msg)

    def warning(self, msg):
        self._log(msg)

    def error(self, msg):
        self._log(msg)


# --------------------------------------------------------------------------
# 1. Resolver: metadados sem baixar
# --------------------------------------------------------------------------

def resolver(url: str, playlist: bool = True,
             cancel: Optional[threading.Event] = None,
             log: Callable[[str], None] = _noop) -> dict:
    """Le os metadados do link. Nao baixa nada.

    Retorna um dicionario:
        {"playlist": bool,
         "titulo": str,            # titulo da playlist, ou do video unico
         "canal": str,
         "itens": [ {"url", "titulo", "duracao_s", "indice"} , ... ]}

    playlist=False forca tratar um link "video dentro de playlist" como video
    unico (e o caso de quem cola o link de um video e nao quer os outros 200).
    """
    _checa_cancelamento(cancel)
    opts = _opcoes_base(log)
    opts.update({
        "skip_download": True,
        # extract_flat: lista a playlist sem abrir cada video. Sem isso, uma
        # playlist de 50 itens levaria minutos em vez de segundos.
        "extract_flat": "in_playlist",
        "noplaylist": not playlist,
    })

    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except DownloadError as e:
        raise BaixarError(_mensagem_amigavel(e)) from e

    _checa_cancelamento(cancel)

    if info.get("_type") == "playlist":
        itens = []
        for i, e in enumerate(info.get("entries") or [], 1):
            if not e:
                continue  # item removido ou privado: o yt-dlp devolve None
            itens.append({
                "url": e.get("url") or e.get("webpage_url"),
                "titulo": e.get("title") or "(sem titulo)",
                "duracao_s": e.get("duration") or 0,
                "indice": i,
            })
        return {
            "playlist": True,
            "titulo": info.get("title") or "(playlist sem titulo)",
            "canal": info.get("uploader") or info.get("channel") or "",
            "itens": itens,
        }

    return {
        "playlist": False,
        "titulo": info.get("title") or "(sem titulo)",
        "canal": info.get("uploader") or info.get("channel") or "",
        "itens": [{
            "url": info.get("webpage_url") or url,
            "titulo": info.get("title") or "(sem titulo)",
            "duracao_s": info.get("duration") or 0,
            "indice": 1,
        }],
    }


# --------------------------------------------------------------------------
# 2. Baixar de fato
# --------------------------------------------------------------------------

def _formato(so_audio: bool) -> str:
    if so_audio:
        # faixa unica de audio: nada para juntar, dispensa ffmpeg
        return "bestaudio[ext=m4a]/bestaudio"
    if ffmpeg_disponivel():
        # melhor video + melhor audio, juntados pelo ffmpeg
        return "bestvideo*+bestaudio/best"
    # sem ffmpeg: so o que ja vem com video e audio no mesmo arquivo
    return "best[vcodec!=none][acodec!=none]/best"


def baixar(url: str, pasta: str, so_audio: bool = True,
           nome: Optional[str] = None,
           progress: Optional[ProgressCb] = None,
           cancel: Optional[threading.Event] = None,
           log: Callable[[str], None] = _noop) -> str:
    """Baixa um item e devolve o caminho do arquivo gravado.

    nome: nome do arquivo SEM extensao. Se None, usa o titulo do video.
    A extensao e escolhida pelo formato que o site entregou.
    """
    _checa_cancelamento(cancel)
    progress = progress or _noop
    os.makedirs(pasta, exist_ok=True)

    # guarda o caminho final visto pelo hook; prepare_filename() nao serve
    # sozinho porque a extensao real so e conhecida depois da escolha do formato
    gravado = {"caminho": None, "total": 0}

    def hook(d):
        # o hook e chamado varias vezes por segundo: e o melhor lugar para
        # perceber o cancelamento sem travar a interface
        if cancel is not None and cancel.is_set():
            raise CanceladoError()
        if d.get("status") == "downloading":
            atual = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            # o total pode oscilar entre fragmentos; segura o maior ja visto
            # para a barra nunca andar para tras
            gravado["total"] = max(gravado["total"], int(total), int(atual))
            progress("baixando", int(atual), gravado["total"])
        elif d.get("status") == "finished":
            gravado["caminho"] = d.get("filename")
            # fecha em 100%. 'finished' e por arquivo: num download de video
            # com merge ele vem uma vez por faixa, e o tamanho final so e
            # conhecido aqui.
            tam = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            gravado["total"] = max(gravado["total"], int(tam))
            progress("baixando", gravado["total"], gravado["total"])

    modelo_nome = (nome + ".%(ext)s") if nome else "%(title)s.%(ext)s"
    opts = _opcoes_base(log)
    opts.update({
        "format": _formato(so_audio),
        "outtmpl": os.path.join(pasta, modelo_nome),
        "progress_hooks": [hook],
        "noplaylist": True,          # aqui e sempre um item so
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,          # retoma download interrompido
        "windowsfilenames": True,    # tira : ? " * | dos titulos
    })

    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
    except CanceladoError:
        raise
    except DownloadError as e:
        # o yt-dlp embrulha o CanceladoError levantado dentro do hook
        if cancel is not None and cancel.is_set():
            raise CanceladoError() from e
        raise BaixarError(_mensagem_amigavel(e)) from e

    # depois de um merge o arquivo final tem outro nome que o do hook
    pedidos = info.get("requested_downloads") or []
    if pedidos and pedidos[0].get("filepath"):
        return pedidos[0]["filepath"]
    if gravado["caminho"] and os.path.isfile(gravado["caminho"]):
        return gravado["caminho"]
    raise BaixarError("o download terminou mas o arquivo nao foi encontrado")


def _mensagem_amigavel(e: Exception) -> str:
    """Traduz o erro do yt-dlp para algo que o usuario final entenda."""
    t = str(e).lower()
    if "private" in t or "sign in" in t or "login" in t:
        return ("Esse video e privado ou exige login. Nao da para baixar sem a "
                "conta que tem acesso.")
    if "age" in t and "confirm" in t:
        return "Esse video tem restricao de idade e exige login para baixar."
    if "unavailable" in t or "removed" in t:
        return "Esse video nao esta mais disponivel."
    if "not a valid url" in t or "unsupported url" in t:
        return "Esse link nao e de um site suportado."
    if "network" in t or "timed out" in t or "connection" in t:
        return "Falha de conexao. Verifique a internet e tente de novo."
    return f"Nao foi possivel baixar: {e}"


# --------------------------------------------------------------------------
# CLI de teste (nao entra na interface)
# --------------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(description="Baixa video/audio de um link.")
    p.add_argument("url")
    p.add_argument("--pasta", default=".")
    p.add_argument("--video", action="store_true",
                   help="baixa o video; sem isso baixa so o audio")
    p.add_argument("--listar", action="store_true",
                   help="so lista a playlist, nao baixa")
    p.add_argument("--item", type=int, default=None,
                   help="baixa apenas o item N da playlist")
    a = p.parse_args()

    info = resolver(a.url, log=lambda m: print(m))
    tipo = "playlist" if info["playlist"] else "video"
    print(f"{tipo}: {info['titulo']}  ({info['canal']})")
    total = sum(i["duracao_s"] for i in info["itens"])
    print(f"{len(info['itens'])} item(ns), {total/3600:.2f} h no total")
    for i in info["itens"]:
        d = i["duracao_s"]
        print(f"  {i['indice']:3d}. {d//60:3d}:{d%60:02d}  {i['titulo'][:56]}")

    if a.listar:
        return 0

    alvos = info["itens"]
    if a.item:
        alvos = [x for x in alvos if x["indice"] == a.item]

    print(f"\nffmpeg disponivel: {ffmpeg_disponivel()}")
    for i in alvos:
        print(f"\nbaixando {i['indice']}: {i['titulo'][:56]}")

        def mostrar(etapa, atual, total_b):
            if total_b:
                print(f"\r  {atual/1e6:6.1f} / {total_b/1e6:.1f} MB", end="")

        nome = f"{i['indice']:02d} - {i['titulo']}" if info["playlist"] else None
        caminho = baixar(i["url"], a.pasta, so_audio=not a.video,
                         nome=nome, progress=mostrar)
        tam = os.path.getsize(caminho) / 1e6
        print(f"\n  -> {caminho}  ({tam:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
