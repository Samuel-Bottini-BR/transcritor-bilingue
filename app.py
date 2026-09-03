# -*- coding: utf-8 -*-
"""Transcritor Bilingue - interface grafica (PySide6).

Layout "bancada": a coluna da esquerda guarda a fila e a biblioteca; o item
selecionado ocupa a mesa. O trabalho roda numa thread separada e a janela
nunca congela.

A esteira tem tres etapas que se ligam e desligam:
    baixar -> transcrever -> traduzir
Traduzir depende de transcrever; a interface desliga sozinha quem ficou sem
dependencia, em vez de deixar o usuario montar uma combinacao impossivel.
"""

import os
import sys
import threading

# registra as DLLs do CUDA antes de qualquer coisa que use ctranslate2
import cuda_setup  # noqa: F401

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSettings, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QFrame, QProgressBar, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QLineEdit, QSplitter,
    QStackedWidget, QScrollArea, QSizePolicy, QComboBox, QTabBar,
)

import fila
import motor
import traduzir

# --------------------------------------------------------------------------
# Vocabulario da interface
# --------------------------------------------------------------------------

IDIOMAS = [
    ("pt", "Portugues"), ("en", "Ingles"), ("it", "Italiano"),
    ("es", "Espanhol"), ("fr", "Frances"), ("de", "Alemao"),
]
PADRAO_MARCADOS = {"en", "it"}

MODELOS = [
    ("large-v3", "Grande", "melhor qualidade, usa a placa de video"),
    ("medium", "Medio", "mais rapido, funciona em qualquer PC"),
    ("small", "Pequeno", "rascunho rapido, menos preciso"),
]

FORMATOS = [("srt", ".srt"), ("vtt", ".vtt"), ("txt", ".txt")]

# Cor por idioma, na ordem em que sao marcados. Mesma regra do desenho: cor
# significa idioma e mais nada. Por isso o botao principal e neutro.
CORES_IDIOMA = ["#b8862f", "#3f8a80", "#6a5aa8", "#9c4f6b", "#2e6699", "#5f7a2e"]

FATOR_TEMPO = {  # multiplo grosseiro da duracao, so para estimar
    ("large-v3", True): 0.20, ("large-v3", False): 3.0,
    ("medium", True): 0.12, ("medium", False): 1.3,
    ("small", True): 0.06, ("small", False): 0.5,
}


def estimar_min(dur_s, modelo, tem_gpu):
    return (dur_s / 60.0) * FATOR_TEMPO.get((modelo, tem_gpu), 2.0)


def texto_duracao(s):
    s = int(s or 0)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s%60:02d}" if h else f"{m}:{s%60:02d}"


def texto_estimativa(mins):
    if mins <= 0:
        return ""
    return f"~{mins/60:.1f} h" if mins >= 60 else f"~{mins:.0f} min"


# --------------------------------------------------------------------------
# Pastas
# --------------------------------------------------------------------------

def _base_gravavel():
    """Pasta gravavel sem admin, tanto empacotado quanto em desenvolvimento."""
    if getattr(sys, "frozen", False):
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "TranscritorBilingue")
    return os.path.dirname(os.path.abspath(__file__))


def pasta_modelos_padrao():
    """Onde procurar os pesos, em ordem de preferencia.

    Procura em varios lugares e fica no primeiro que JA tiver modelo: baixar
    4,5 GB de novo por causa de caminho e o pior desperdicio possivel aqui.

    A pasta ao lado do executavel importa por dois motivos: no app congelado
    __file__ aponta para dentro do bundle (a pasta do projeto fica invisivel),
    e ela permite uma instalacao portatil levar os modelos junto.
    """
    candidatos = [os.path.join(_base_gravavel(), "modelos")]
    if getattr(sys, "frozen", False):
        candidatos.append(
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                         "modelos"))
    candidatos += [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos"),
        os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                     "TranscritorBilingue", "modelos"),
    ]
    vistos = []
    for c in candidatos:
        if c not in vistos:
            vistos.append(c)
    for c in vistos:
        if os.path.isdir(c) and os.listdir(c):
            return c
    return vistos[0]


def pasta_videos_padrao():
    perfil = os.path.expanduser("~")
    for nome in ("Videos", "Video", "Meus Videos"):
        p = os.path.join(perfil, nome)
        if os.path.isdir(p):
            return os.path.join(p, "Transcritor")
    return os.path.join(perfil, "Transcritor")


# --------------------------------------------------------------------------
# Widgets pequenos
# --------------------------------------------------------------------------

class BotoesIdioma(QWidget):
    """Fileira de idiomas que se marcam e desmarcam, com a cor da pista."""

    mudou = Signal()

    def __init__(self, marcados=(), com_cor=True):
        super().__init__()
        self.com_cor = com_cor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.botoes = {}
        for cod, nome in IDIOMAS:
            b = QPushButton(nome)
            b.setCheckable(True)
            b.setChecked(cod in marcados)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("classe", "idioma")
            b.clicked.connect(self._mudou)
            self.botoes[cod] = b
            lay.addWidget(b)
        lay.addStretch()
        self._pintar()

    def _mudou(self):
        self._pintar()
        self.mudou.emit()

    def _pintar(self):
        if not self.com_cor:
            return
        # a cor sai da ORDEM de marcacao, igual as pistas do mapa de idiomas
        i = 0
        for cod, b in self.botoes.items():
            if b.isChecked():
                cor = CORES_IDIOMA[i % len(CORES_IDIOMA)]
                b.setStyleSheet(
                    f"QPushButton{{border:1px solid {cor};"
                    f"background:{cor}22;color:palette(text);}}")
                i += 1
            else:
                b.setStyleSheet("")

    def marcados(self):
        return [c for c, b in self.botoes.items() if b.isChecked()]

    def definir(self, codigos):
        for c, b in self.botoes.items():
            b.setChecked(c in codigos)
        self._pintar()

    def limitar_a(self, permitidos):
        """Esconde idiomas que o modelo de traducao nao cobre."""
        for c, b in self.botoes.items():
            b.setVisible(c in permitidos)


class Etapa(QFrame):
    """Uma etapa da esteira: cabecalho com interruptor + corpo com os ajustes."""

    mudou = Signal()

    def __init__(self, numero, titulo, dica):
        super().__init__()
        self.setObjectName("etapa")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        topo = QHBoxLayout()
        self.num = QLabel(str(numero))
        self.num.setObjectName("numEtapa")
        self.num.setFixedSize(26, 26)
        self.num.setAlignment(Qt.AlignCenter)
        self.titulo = QLabel(titulo)
        self.titulo.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        self.dica = QLabel(dica)
        self.dica.setObjectName("dica")
        self.chave = QCheckBox("ligado")
        self.chave.setChecked(True)
        self.chave.toggled.connect(self._alternou)
        topo.addWidget(self.num)
        topo.addWidget(self.titulo)
        topo.addWidget(self.dica)
        topo.addStretch()
        topo.addWidget(self.chave)
        lay.addLayout(topo)

        self.corpo = QWidget()
        self.corpo_lay = QVBoxLayout(self.corpo)
        self.corpo_lay.setContentsMargins(36, 0, 0, 0)
        self.corpo_lay.setSpacing(8)
        lay.addWidget(self.corpo)

    def _alternou(self, ligado):
        """Slot do interruptor: muda o visual E avisa quem observa."""
        self._aplicar(ligado)
        self.chave.setText("ligado" if ligado else "desligado")
        self.mudou.emit()

    def _aplicar(self, ligado):
        """So o visual, sem emitir. Usado por travar()/destravar(), que sao
        chamados de DENTRO do tratamento de mudou - emitir dali criaria
        recursao infinita."""
        self.corpo.setVisible(ligado)
        self.setProperty("desligado", not ligado)
        self.style().unpolish(self)
        self.style().polish(self)

    def ligado(self):
        return self.chave.isChecked()

    def definir_ligado(self, v):
        self.chave.setChecked(v)
        self._alternou(v)

    def travar(self, motivo):
        """Desliga e explica por que nao da para ligar. Nao emite."""
        self.chave.blockSignals(True)
        self.chave.setChecked(False)
        self.chave.setEnabled(False)
        self.chave.blockSignals(False)
        self._aplicar(False)
        self.chave.setText(motivo)   # depois de _aplicar, senao seria sobrescrito

    def destravar(self):
        if self.chave.isEnabled():
            return
        self.chave.setEnabled(True)
        self.chave.setText("ligado" if self.chave.isChecked() else "desligado")

    def adicionar(self, w):
        self.corpo_lay.addWidget(w)


def rotulo(texto):
    lb = QLabel(texto.upper())
    lb.setObjectName("rotulo")
    return lb


# --------------------------------------------------------------------------
# Ponte thread -> interface
# --------------------------------------------------------------------------

class Corredor(QObject):
    """Roda o Executor numa thread e reemite os eventos como sinais Qt.

    O Executor chama os callbacks da thread de trabalho; tocar em widget dali
    trava a interface. Todo evento vira sinal, que o Qt entrega na thread da
    janela.
    """

    mudou = Signal(object)
    log = Signal(str)
    acabou = Signal()

    def __init__(self, cfg, trabalhos):
        super().__init__()
        self.cfg = cfg
        self.trabalhos = trabalhos
        self.executor = fila.Executor(
            cfg, ao_mudar=self.mudou.emit, ao_log=self.log.emit)

    def cancelar(self):
        self.executor.cancelar()

    def rodar(self):
        try:
            self.executor.rodar(self.trabalhos)
        finally:
            self.acabou.emit()


class Resolvedor(QObject):
    """Resolve um link (playlist inclusive) fora da thread da interface."""

    pronto = Signal(object)
    falhou = Signal(str)

    def __init__(self, url, padrao):
        super().__init__()
        self.url = url
        self.padrao = padrao
        self.cancel = threading.Event()

    def rodar(self):
        try:
            self.pronto.emit(fila.de_link(self.url, self.padrao,
                                          cancel=self.cancel))
        except Exception as e:
            self.falhou.emit(str(e))


# --------------------------------------------------------------------------
# Painel de pastas
# --------------------------------------------------------------------------

class PainelPastas(QWidget):
    mudou = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(16)

        t = QLabel("Pastas")
        t.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
        lay.addWidget(t)
        sub = QLabel("Vale para tudo que entrar daqui em diante.")
        sub.setObjectName("dica")
        lay.addWidget(sub)

        self.campos = {}
        for chave, nome in (("pasta_midia", "Videos e audios baixados"),
                            ("pasta_legendas", "Legendas"),
                            ("pasta_modelos", "Modelos")):
            lay.addWidget(rotulo(nome))
            linha = QHBoxLayout()
            campo = QLineEdit(getattr(cfg, chave))
            campo.editingFinished.connect(
                lambda c=chave: self._digitou(c))
            b1 = QPushButton("Escolher...")
            b1.clicked.connect(lambda _, c=chave: self._escolher(c))
            b2 = QPushButton("Abrir")
            b2.clicked.connect(lambda _, c=chave: self._abrir(c))
            linha.addWidget(campo, 1)
            linha.addWidget(b1)
            linha.addWidget(b2)
            lay.addLayout(linha)
            self.campos[chave] = campo

        lay.addWidget(rotulo("Como organizar"))
        self.org = QComboBox()
        self.org.addItem("Tudo junto na mesma pasta", fila.JUNTO)
        self.org.addItem("Uma subpasta por playlist", fila.POR_PLAYLIST)
        self.org.addItem("Ao lado do video de origem", fila.AO_LADO)
        i = self.org.findData(cfg.organizacao)
        self.org.setCurrentIndex(max(0, i))
        self.org.currentIndexChanged.connect(self._org)
        lay.addWidget(self.org)
        self.expl = QLabel()
        self.expl.setObjectName("dica")
        self.expl.setWordWrap(True)
        lay.addWidget(self.expl)

        lay.addWidget(rotulo("Depois de transcrever"))
        self.guardar = QCheckBox("Guardar o video baixado")
        self.guardar.setChecked(cfg.guardar_midia)
        self.guardar.toggled.connect(self._guardar)
        lay.addWidget(self.guardar)
        av = QLabel("Apagar libera espaco, mas obriga a baixar de novo se voce "
                    "quiser refazer a legenda com outro modelo.")
        av.setObjectName("dica")
        av.setWordWrap(True)
        lay.addWidget(av)

        lay.addStretch()
        self._org()

    def _digitou(self, chave):
        setattr(self.cfg, chave, self.campos[chave].text().strip())
        self.mudou.emit()

    def _escolher(self, chave):
        d = QFileDialog.getExistingDirectory(self, "Escolha a pasta",
                                             getattr(self.cfg, chave) or "")
        if d:
            setattr(self.cfg, chave, d)
            self.campos[chave].setText(d)
            self.mudou.emit()

    def _abrir(self, chave):
        d = getattr(self.cfg, chave)
        if d:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)

    def _org(self):
        self.cfg.organizacao = self.org.currentData()
        textos = {
            fila.JUNTO: "Todas as legendas caem na mesma pasta.",
            fila.POR_PLAYLIST:
                "Uma playlist de 9 videos vira uma subpasta com o nome dela, "
                "com os arquivos numerados na ordem.",
            fila.AO_LADO:
                "A legenda fica junto do video. So funciona para arquivos que "
                "ja estao no seu computador ou que voce mandou baixar.",
        }
        self.expl.setText(textos.get(self.cfg.organizacao, ""))
        self.mudou.emit()

    def _guardar(self, v):
        self.cfg.guardar_midia = v
        self.mudou.emit()


# --------------------------------------------------------------------------
# Painel do trabalho selecionado
# --------------------------------------------------------------------------

class PainelTrabalho(QWidget):
    mudou = Signal()

    def __init__(self, cfg, tem_gpu):
        super().__init__()
        self.cfg = cfg
        self.tem_gpu = tem_gpu
        self.t = None
        self._carregando = False

        fora = QVBoxLayout(self)
        fora.setContentsMargins(0, 0, 0, 0)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        fora.addWidget(rolagem)

        dentro = QWidget()
        rolagem.setWidget(dentro)
        lay = QVBoxLayout(dentro)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)

        self.titulo = QLabel("Nada selecionado")
        self.titulo.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
        self.titulo.setWordWrap(True)
        lay.addWidget(self.titulo)
        self.meta = QLabel("")
        self.meta.setObjectName("dica")
        self.meta.setWordWrap(True)
        lay.addWidget(self.meta)

        # ---- etapa 1 ----
        self.e1 = Etapa(1, "Baixar", "do link")
        self.midia = QComboBox()
        self.midia.addItem("So o audio - mais rapido e leve", False)
        self.midia.addItem("Video completo", True)
        self.midia.currentIndexChanged.connect(self._recolher)
        self.e1.adicionar(self.midia)
        self.aviso_ffmpeg = QLabel()
        self.aviso_ffmpeg.setObjectName("aviso")
        self.aviso_ffmpeg.setWordWrap(True)
        self.aviso_ffmpeg.setVisible(False)
        self.e1.adicionar(self.aviso_ffmpeg)
        self.e1.mudou.connect(self._recolher)
        lay.addWidget(self.e1)

        # ---- etapa 2 ----
        self.e2 = Etapa(2, "Transcrever", "o audio vira texto com tempos")
        self.e2.adicionar(rotulo("Idiomas falados no video"))
        self.idiomas = BotoesIdioma(PADRAO_MARCADOS)
        self.idiomas.mudou.connect(self._recolher)
        self.e2.adicionar(self.idiomas)
        d = QLabel("Marque todos os que aparecem. E isso que impede a legenda "
                   "de travar num idioma so.")
        d.setObjectName("dica")
        d.setWordWrap(True)
        self.e2.adicionar(d)
        self.e2.adicionar(rotulo("Qualidade"))
        linha_q = QHBoxLayout()
        self.qualidade = {}
        caixa_q = QWidget()
        caixa_q.setLayout(linha_q)
        linha_q.setContentsMargins(0, 0, 0, 0)
        for cod, nome, _dica in MODELOS:
            b = QPushButton(nome)
            b.setCheckable(True)
            b.setChecked(cod == "large-v3")
            b.clicked.connect(lambda _, c=cod: self._qualidade(c))
            self.qualidade[cod] = b
            linha_q.addWidget(b)
        linha_q.addStretch()
        self.e2.adicionar(caixa_q)
        self.dica_q = QLabel("")
        self.dica_q.setObjectName("dica")
        self.e2.adicionar(self.dica_q)
        self.e2.mudou.connect(self._recolher)
        lay.addWidget(self.e2)

        # ---- etapa 3 ----
        self.e3 = Etapa(3, "Traduzir", "a legenda vira outro idioma")
        self.e3.definir_ligado(False)
        self.e3.adicionar(rotulo("Traduzir para"))
        self.alvos = BotoesIdioma(())
        self.alvos.limitar_a(set(traduzir.CODIGOS) - {"la"})
        self.alvos.mudou.connect(self._recolher)
        self.e3.adicionar(self.alvos)
        dt = QLabel("Usa um segundo modelo (~647 MB, baixado uma vez). A linha "
                    "que ja esta no idioma de destino nao e traduzida.")
        dt.setObjectName("dica")
        dt.setWordWrap(True)
        self.e3.adicionar(dt)
        self.e3.mudou.connect(self._recolher)
        lay.addWidget(self.e3)

        # ---- saida ----
        lay.addWidget(rotulo("Formatos e nome"))
        linha_f = QHBoxLayout()
        self.formatos = {}
        for cod, nome in FORMATOS:
            c = QCheckBox(nome)
            c.setChecked(cod == "srt")
            c.toggled.connect(self._recolher)
            self.formatos[cod] = c
            linha_f.addWidget(c)
        self.chk_relatorio = QCheckBox("relatorio .json")
        self.chk_relatorio.setChecked(True)
        self.chk_relatorio.toggled.connect(self._recolher)
        linha_f.addWidget(self.chk_relatorio)
        self.chk_marcar = QCheckBox("marcar idioma na linha")
        self.chk_marcar.toggled.connect(self._recolher)
        linha_f.addWidget(self.chk_marcar)
        linha_f.addStretch()
        lay.addLayout(linha_f)

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("nome do arquivo (sem extensao)")
        self.nome.editingFinished.connect(self._recolher)
        lay.addWidget(self.nome)

        # ---- previsao ----
        self.cab_saida = rotulo("Vai gerar")
        lay.addWidget(self.cab_saida)
        self.lista_saida = QLabel("")
        self.lista_saida.setObjectName("saida")
        self.lista_saida.setWordWrap(True)
        self.lista_saida.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lista_saida)

        lay.addStretch()

    # -- ligacao com o Trabalho ---------------------------------------

    def mostrar(self, t):
        self.t = t
        self._carregando = True
        if t is None:
            self.titulo.setText("Nada selecionado")
            self.meta.setText("Adicione um arquivo ou cole um link acima.")
            self._carregando = False
            return
        self.titulo.setText(t.titulo or os.path.basename(t.origem))
        self.e1.setVisible(t.e_url)
        self.e1.definir_ligado(t.baixar_ligado)
        self.midia.setCurrentIndex(1 if t.baixar_video else 0)
        self.e2.definir_ligado(t.transcrever_ligado)
        self.idiomas.definir(t.idiomas)
        for cod, b in self.qualidade.items():
            b.setChecked(cod == t.modelo)
        self.e3.definir_ligado(t.traduzir_ligado)
        self.alvos.definir(t.traduzir_para)
        for cod, c in self.formatos.items():
            c.setChecked(cod in t.formatos)
        self.chk_relatorio.setChecked(t.relatorio)
        self.chk_marcar.setChecked(t.marcar_idioma)
        self.nome.setText(t.nome_saida)
        self._carregando = False
        self._recolher()

    def _qualidade(self, escolhido):
        for cod, b in self.qualidade.items():
            b.setChecked(cod == escolhido)
        self._recolher()

    def _modelo(self):
        for cod, b in self.qualidade.items():
            if b.isChecked():
                return cod
        return "large-v3"

    def _recolher(self):
        """Le os widgets de volta para o Trabalho e atualiza a previsao.

        Reentrante por natureza: daqui mexemos em widgets que emitem sinais
        ligados de volta neste metodo. A trava evita a recursao; sem ela,
        desligar a etapa 2 estoura a pilha.
        """
        if self._carregando or self.t is None or getattr(self, "_dentro", False):
            return
        self._dentro = True
        try:
            self._recolher_mesmo()
        finally:
            self._dentro = False

    def _recolher_mesmo(self):
        t = self.t
        t.baixar_ligado = self.e1.ligado() and t.e_url
        t.baixar_video = bool(self.midia.currentData())
        t.transcrever_ligado = self.e2.ligado()
        t.idiomas = self.idiomas.marcados()
        t.modelo = self._modelo()
        t.traduzir_ligado = self.e3.ligado()
        t.traduzir_para = self.alvos.marcados()
        t.formatos = [c for c, w in self.formatos.items() if w.isChecked()]
        t.relatorio = self.chk_relatorio.isChecked()
        t.marcar_idioma = self.chk_marcar.isChecked()
        t.nome_saida = self.nome.text().strip()

        # dependencia: traduzir precisa de transcrever
        if not t.transcrever_ligado:
            self.e3.travar("precisa da etapa 2")
            t.traduzir_ligado = False
        else:
            self.e3.destravar()

        # aviso do ffmpeg so quando ele importa
        import baixar as _b
        precisa = t.baixar_video and not _b.ffmpeg_disponivel()
        self.aviso_ffmpeg.setVisible(precisa)
        if precisa:
            self.aviso_ffmpeg.setText(
                "Sem ffmpeg no computador: o video vem no formato ja pronto, "
                "que no YouTube costuma parar em 720p.")

        mins = estimar_min(t.duracao_s, t.modelo, self.tem_gpu)
        est = texto_estimativa(mins)
        partes = [texto_duracao(t.duracao_s)] if t.duracao_s else []
        if t.playlist:
            partes.append(f"playlist {t.playlist}")
        if est and t.transcrever_ligado:
            partes.append(f"transcricao {est}")
        partes.append("GPU" if self.tem_gpu else "CPU - pode demorar horas")
        self.meta.setText("  ·  ".join(partes))

        for cod, nome, dica in MODELOS:
            if cod == t.modelo:
                self.dica_q.setText(dica)

        prev = t.arquivos_previstos(self.cfg)
        self.cab_saida.setText(
            f"VAI GERAR {len(prev)} ARQUIVO{'S' if len(prev) != 1 else ''}")
        linhas = []
        for caminho, tipo in prev:
            linhas.append(f"<b>{tipo}</b> &nbsp; {os.path.basename(caminho)}")
        pasta = self.cfg.destino_legenda(t)
        linhas.append(f"<span style='color:#888'>em {pasta}</span>")
        self.lista_saida.setText("<br>".join(linhas))
        self.mudou.emit()


# --------------------------------------------------------------------------
# Area de soltar arquivos
# --------------------------------------------------------------------------

class BarraEntrada(QFrame):
    arquivos = Signal(list)
    link = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("barraEntrada")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(9)

        self.alvo = QLabel("Arraste arquivos aqui")
        self.alvo.setObjectName("alvoSoltar")
        lay.addWidget(self.alvo)

        b = QPushButton("Procurar...")
        b.clicked.connect(self._procurar)
        lay.addWidget(b)

        self.campo = QLineEdit()
        self.campo.setPlaceholderText(
            "ou cole um link do YouTube (playlist tambem) e tecle Enter")
        self.campo.returnPressed.connect(self._link)
        lay.addWidget(self.campo, 1)

        self.b_add = QPushButton("Adicionar")
        self.b_add.clicked.connect(self._link)
        lay.addWidget(self.b_add)

    def _procurar(self):
        cs, _ = QFileDialog.getOpenFileNames(
            self, "Escolha videos ou audios", "",
            "Midia (*.mp4 *.mkv *.avi *.mov *.webm *.mp3 *.wav *.m4a *.flac "
            "*.aac *.ogg);;Todos os arquivos (*.*)")
        if cs:
            self.arquivos.emit(cs)

    def _link(self):
        u = self.campo.text().strip()
        if u:
            self.link.emit(u)

    def limpar(self):
        self.campo.clear()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("ativo", True)
            self._repintar()

    def dragLeaveEvent(self, _e):
        self.setProperty("ativo", False)
        self._repintar()

    def dropEvent(self, e):
        self.setProperty("ativo", False)
        self._repintar()
        cs = [u.toLocalFile() for u in e.mimeData().urls()
              if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if cs:
            self.arquivos.emit(cs)

    def _repintar(self):
        self.style().unpolish(self)
        self.style().polish(self)


# --------------------------------------------------------------------------
# Janela
# --------------------------------------------------------------------------

class Janela(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transcritor Bilingue")
        self.resize(1180, 780)
        self.tem_gpu = motor.gpu_disponivel()
        self.trabalhos = []
        self.thread = None
        self.corredor = None
        self.thread_res = None
        self.resolvedor = None

        self.settings = QSettings("TranscritorBilingue", "app")
        self.cfg = self._carregar_config()
        # modelo de configuracao herdado pelos proximos trabalhos adicionados
        self.padrao = fila.Trabalho(
            origem="", idiomas=sorted(PADRAO_MARCADOS), modelo="large-v3")

        central = QWidget()
        self.setCentralWidget(central)
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        self.barra = BarraEntrada()
        self.barra.arquivos.connect(self.adicionar_arquivos)
        self.barra.link.connect(self.adicionar_link)
        raiz.addWidget(self.barra)

        divisor = QSplitter(Qt.Horizontal)
        raiz.addWidget(divisor, 1)

        # ---- coluna esquerda ----
        esq = QWidget()
        esq.setObjectName("coluna")
        lay_esq = QVBoxLayout(esq)
        lay_esq.setContentsMargins(0, 0, 0, 0)
        lay_esq.setSpacing(0)

        self.abas = QTabBar()
        self.abas.addTab("Fila")
        self.abas.addTab("Biblioteca")
        self.abas.currentChanged.connect(self._trocar_aba)
        lay_esq.addWidget(self.abas)

        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._selecionou)
        lay_esq.addWidget(self.lista, 1)

        self.biblioteca = QListWidget()
        self.biblioteca.setVisible(False)
        self.biblioteca.itemDoubleClicked.connect(self._abrir_biblioteca)
        lay_esq.addWidget(self.biblioteca, 1)

        rodape = QWidget()
        lay_rod = QVBoxLayout(rodape)
        lay_rod.setContentsMargins(10, 10, 10, 10)
        lay_rod.setSpacing(7)
        self.btn_comecar = QPushButton("Comecar a fila")
        self.btn_comecar.setObjectName("primario")
        self.btn_comecar.setMinimumHeight(36)
        self.btn_comecar.clicked.connect(self.comecar)
        lay_rod.addWidget(self.btn_comecar)
        linha_r = QHBoxLayout()
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setEnabled(False)
        self.btn_cancelar.clicked.connect(self.cancelar)
        self.btn_pastas = QPushButton("Pastas...")
        self.btn_pastas.setCheckable(True)
        self.btn_pastas.clicked.connect(self._alternar_pastas)
        self.btn_remover = QPushButton("Remover")
        self.btn_remover.clicked.connect(self.remover)
        linha_r.addWidget(self.btn_remover)
        linha_r.addWidget(self.btn_cancelar)
        linha_r.addWidget(self.btn_pastas)
        lay_rod.addLayout(linha_r)
        self.resumo_fila = QLabel("Fila vazia")
        self.resumo_fila.setObjectName("dica")
        self.resumo_fila.setWordWrap(True)
        lay_rod.addWidget(self.resumo_fila)
        lay_esq.addWidget(rodape)

        divisor.addWidget(esq)

        # ---- mesa ----
        self.mesa = QStackedWidget()
        self.painel = PainelTrabalho(self.cfg, self.tem_gpu)
        self.painel.mudou.connect(self._atualizar_linha_atual)
        self.pastas = PainelPastas(self.cfg)
        self.pastas.mudou.connect(self._config_mudou)
        self.mesa.addWidget(self.painel)
        self.mesa.addWidget(self.pastas)
        divisor.addWidget(self.mesa)

        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([300, 880])

        # ---- barra de progresso global ----
        base = QWidget()
        lay_base = QHBoxLayout(base)
        lay_base.setContentsMargins(14, 8, 14, 10)
        self.lbl_etapa = QLabel("")
        self.barra_prog = QProgressBar()
        self.barra_prog.setTextVisible(False)
        self.barra_prog.setFixedHeight(16)
        lay_base.addWidget(self.lbl_etapa, 1)
        lay_base.addWidget(self.barra_prog, 2)
        raiz.addWidget(base)

        self.setStyleSheet(ESTILO)
        self._avisar_gpu()
        self._atualizar_resumo()
        self.painel.mostrar(None)

    # -- config -------------------------------------------------------

    def _carregar_config(self):
        base = pasta_videos_padrao()
        s = self.settings
        return fila.Config(
            pasta_midia=s.value("pasta_midia", os.path.join(base, "baixados")),
            pasta_legendas=s.value("pasta_legendas",
                                   os.path.join(base, "legendas")),
            pasta_modelos=s.value("pasta_modelos", pasta_modelos_padrao()),
            organizacao=s.value("organizacao", fila.POR_PLAYLIST),
            guardar_midia=s.value("guardar_midia", True, type=bool),
        )

    def _config_mudou(self):
        s = self.settings
        s.setValue("pasta_midia", self.cfg.pasta_midia)
        s.setValue("pasta_legendas", self.cfg.pasta_legendas)
        s.setValue("pasta_modelos", self.cfg.pasta_modelos)
        s.setValue("organizacao", self.cfg.organizacao)
        s.setValue("guardar_midia", self.cfg.guardar_midia)
        if self.painel.t:
            self.painel._recolher()

    def _avisar_gpu(self):
        if not self.tem_gpu:
            self.lbl_etapa.setText(
                "Sem placa de video compativel: vai rodar na CPU, o que pode "
                "levar horas.")

    # -- entrada ------------------------------------------------------

    def adicionar_arquivos(self, caminhos):
        novos = fila.de_arquivos(caminhos, self.padrao)
        self._adicionar(novos)

    def adicionar_link(self, url):
        self.barra.b_add.setEnabled(False)
        self.lbl_etapa.setText("Lendo o link...")
        self.thread_res = QThread()
        self.resolvedor = Resolvedor(url, self.padrao)
        self.resolvedor.moveToThread(self.thread_res)
        self.thread_res.started.connect(self.resolvedor.rodar)
        self.resolvedor.pronto.connect(self._link_pronto)
        self.resolvedor.falhou.connect(self._link_falhou)
        self.thread_res.start()

    def _link_pronto(self, novos):
        self._fechar_resolvedor()
        self.barra.limpar()
        if novos and novos[0].playlist:
            self.lbl_etapa.setText(
                f"Playlist \"{novos[0].playlist}\": {len(novos)} videos "
                f"adicionados.")
        else:
            self.lbl_etapa.setText("1 video adicionado.")
        self._adicionar(novos)

    def _link_falhou(self, msg):
        self._fechar_resolvedor()
        self.lbl_etapa.setText("")
        QMessageBox.warning(self, "Nao consegui ler o link", msg)

    def _fechar_resolvedor(self):
        self.barra.b_add.setEnabled(True)
        if self.thread_res:
            self.thread_res.quit()
            self.thread_res.wait()
            self.thread_res = None
            self.resolvedor = None

    def _adicionar(self, novos):
        if not novos:
            return
        self.trabalhos.extend(novos)
        self._reconstruir_lista()
        self.lista.setCurrentRow(len(self.trabalhos) - 1)
        self._atualizar_resumo()

    def remover(self):
        i = self.lista.currentRow()
        if 0 <= i < len(self.trabalhos):
            if self.trabalhos[i].estado == fila.RODANDO:
                QMessageBox.information(
                    self, "Em andamento",
                    "Esse item esta rodando. Cancele a fila antes de remover.")
                return
            del self.trabalhos[i]
            self._reconstruir_lista()
            self._atualizar_resumo()

    # -- lista --------------------------------------------------------

    def _reconstruir_lista(self):
        self.lista.blockSignals(True)
        atual = self.lista.currentRow()
        self.lista.clear()
        grupo_visto = None
        for t in self.trabalhos:
            if t.playlist and t.playlist != grupo_visto:
                cab = QListWidgetItem(f"  {t.playlist.upper()}")
                cab.setFlags(Qt.NoItemFlags)
                cab.setForeground(QColor("#888"))
                f = cab.font()
                # pointSize() devolve -1 quando a fonte foi definida em pixels
                # (e o caso quando a folha de estilo usa font-size em px);
                # mexer no tamanho nesse caso gera aviso do Qt e nao adianta.
                if f.pointSize() > 0:
                    f.setPointSize(max(7, f.pointSize() - 1))
                f.setBold(True)
                cab.setFont(f)
                self.lista.addItem(cab)
                grupo_visto = t.playlist
            elif not t.playlist:
                grupo_visto = None
            self.lista.addItem(QListWidgetItem(self._texto_item(t)))
        self.lista.blockSignals(False)
        if 0 <= atual < self.lista.count():
            self.lista.setCurrentRow(atual)

    def _texto_item(self, t):
        marcas = {fila.ESPERA: "·", fila.RODANDO: "»", fila.PRONTO: "✓",
                  fila.ERRO: "✗", fila.CANCELADO: "-"}
        nome = t.titulo or os.path.basename(t.origem)
        if t.indice:
            nome = f"{t.indice}. {nome}"
        extra = ""
        if t.estado == fila.RODANDO:
            nome_etapa = fila.ETAPAS.get(t.etapa, t.etapa)
            pct = f" {t.atual*100//t.total}%" if t.total else ""
            extra = f"\n     {nome_etapa}{pct}"
        elif t.estado == fila.PRONTO and t.resumo:
            extra = f"\n     {t.resumo.get('aceitos', 0)} legendas"
        elif t.estado == fila.ERRO:
            extra = f"\n     {t.erro[:44]}"
        elif t.duracao_s:
            extra = f"\n     {texto_duracao(t.duracao_s)}"
        return f"{marcas.get(t.estado, '·')} {nome[:42]}{extra}"

    def _indice_trabalho(self, linha):
        """Converte linha da lista (que tem cabecalhos) em indice do trabalho."""
        contador = -1
        grupo_visto = None
        for i, t in enumerate(self.trabalhos):
            if t.playlist and t.playlist != grupo_visto:
                contador += 1
                grupo_visto = t.playlist
            elif not t.playlist:
                grupo_visto = None
            contador += 1
            if contador == linha:
                return i
        return -1

    def _linha_do_trabalho(self, indice):
        contador = -1
        grupo_visto = None
        for i, t in enumerate(self.trabalhos):
            if t.playlist and t.playlist != grupo_visto:
                contador += 1
                grupo_visto = t.playlist
            elif not t.playlist:
                grupo_visto = None
            contador += 1
            if i == indice:
                return contador
        return -1

    def _selecionou(self, linha):
        i = self._indice_trabalho(linha)
        if self.btn_pastas.isChecked():
            self.btn_pastas.setChecked(False)
            self.mesa.setCurrentWidget(self.painel)
        self.painel.mostrar(self.trabalhos[i] if 0 <= i < len(self.trabalhos)
                            else None)

    def _atualizar_linha_atual(self):
        if self.painel.t is None:
            return
        try:
            i = self.trabalhos.index(self.painel.t)
        except ValueError:
            return
        linha = self._linha_do_trabalho(i)
        item = self.lista.item(linha)
        if item:
            item.setText(self._texto_item(self.painel.t))
        self._atualizar_resumo()

    def _atualizar_resumo(self):
        n = len(self.trabalhos)
        if not n:
            self.resumo_fila.setText("Fila vazia")
            return
        dur = sum(t.duracao_s for t in self.trabalhos
                  if t.estado in (fila.ESPERA, fila.ERRO))
        pend = sum(1 for t in self.trabalhos if t.estado == fila.ESPERA)
        mins = sum(estimar_min(t.duracao_s, t.modelo, self.tem_gpu)
                   for t in self.trabalhos
                   if t.estado == fila.ESPERA and t.transcrever_ligado)
        est = texto_estimativa(mins)
        self.resumo_fila.setText(
            f"{n} item(ns), {pend} na fila · {texto_duracao(dur)} de material"
            + (f" · {est}" if est else ""))

    # -- pastas / biblioteca -------------------------------------------

    def _alternar_pastas(self, ligado):
        self.mesa.setCurrentWidget(self.pastas if ligado else self.painel)

    def _trocar_aba(self, i):
        self.lista.setVisible(i == 0)
        self.biblioteca.setVisible(i == 1)
        if i == 1:
            self._encher_biblioteca()

    def _encher_biblioteca(self):
        """Lista o que ja existe nas pastas: baixado, transcrito, ou os dois."""
        self.biblioteca.clear()
        achados = {}
        exts_midia = {".mp4", ".mkv", ".m4a", ".webm", ".mp3", ".wav", ".avi",
                      ".mov", ".flac", ".aac", ".ogg"}
        exts_leg = {".srt", ".vtt", ".txt"}
        for pasta, grupo in ((self.cfg.pasta_midia, "midia"),
                             (self.cfg.pasta_legendas, "legenda")):
            if not pasta or not os.path.isdir(pasta):
                continue
            for raiz, _dirs, arqs in os.walk(pasta):
                for a in arqs:
                    nome, ext = os.path.splitext(a)
                    ext = ext.lower()
                    if grupo == "midia" and ext not in exts_midia:
                        continue
                    if grupo == "legenda" and ext not in exts_leg:
                        continue
                    if nome.endswith("_relatorio"):
                        continue
                    # "filme.en" e traducao de "filme": agrupa no mesmo item
                    chave = nome.rsplit(".", 1)[0] if (
                        "." in nome and len(nome.rsplit(".", 1)[1]) <= 3
                    ) else nome
                    reg = achados.setdefault(
                        chave, {"midia": False, "legenda": False,
                                "caminho": None})
                    reg[grupo] = True
                    if grupo == "midia":
                        reg["caminho"] = os.path.join(raiz, a)
                    elif not reg["caminho"]:
                        reg["caminho"] = os.path.join(raiz, a)
        if not achados:
            it = QListWidgetItem(
                "  Nada ainda.\n  O que voce baixar e transcrever aparece aqui.")
            it.setFlags(Qt.NoItemFlags)
            self.biblioteca.addItem(it)
            return
        for chave in sorted(achados):
            r = achados[chave]
            selos = []
            if r["midia"]:
                selos.append("baixado")
            if r["legenda"]:
                selos.append("transcrito")
            it = QListWidgetItem(f"{chave[:44]}\n     {' · '.join(selos)}")
            it.setData(Qt.UserRole, r["caminho"])
            self.biblioteca.addItem(it)

    def _abrir_biblioteca(self, item):
        caminho = item.data(Qt.UserRole)
        if caminho and os.path.exists(caminho):
            import subprocess
            subprocess.Popen(["explorer", "/select,",
                              os.path.normpath(caminho)])

    # -- execucao ------------------------------------------------------

    def comecar(self):
        pendentes = [t for t in self.trabalhos
                     if t.estado in (fila.ESPERA, fila.ERRO)]
        if not pendentes:
            QMessageBox.information(self, "Nada a fazer",
                                    "Nao ha item pendente na fila.")
            return
        ruins = [t for t in pendentes
                 if t.transcrever_ligado and not t.idiomas]
        if ruins:
            QMessageBox.warning(
                self, "Falta o idioma",
                f"{len(ruins)} item(ns) estao sem idioma marcado. Marque pelo "
                f"menos um idioma falado no video.")
            return
        if not self.tem_gpu:
            mins = sum(estimar_min(t.duracao_s, t.modelo, False)
                       for t in pendentes)
            r = QMessageBox.question(
                self, "Sem placa de video",
                "Nao encontrei uma placa de video compativel. Na CPU isso pode "
                "ser MUITO lento.\n\nEstimativa para a fila: "
                f"{texto_estimativa(mins)}.\n\nQuer continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return

        for p in (self.cfg.pasta_midia, self.cfg.pasta_legendas,
                  self.cfg.pasta_modelos):
            if p:
                os.makedirs(p, exist_ok=True)

        self.btn_comecar.setEnabled(False)
        self.btn_cancelar.setEnabled(True)
        self.barra.setEnabled(False)

        self.thread = QThread()
        self.corredor = Corredor(self.cfg, pendentes)
        self.corredor.moveToThread(self.thread)
        self.thread.started.connect(self.corredor.rodar)
        self.corredor.mudou.connect(self._trabalho_mudou)
        self.corredor.log.connect(self._log)
        self.corredor.acabou.connect(self._acabou)
        self.thread.start()

    def cancelar(self):
        if self.corredor:
            self.corredor.cancelar()
            self.lbl_etapa.setText("Cancelando...")
            self.btn_cancelar.setEnabled(False)

    def _trabalho_mudou(self, t):
        try:
            i = self.trabalhos.index(t)
        except ValueError:
            return
        linha = self._linha_do_trabalho(i)
        item = self.lista.item(linha)
        if item:
            item.setText(self._texto_item(t))
        if t.estado == fila.RODANDO:
            nome = fila.ETAPAS.get(t.etapa, t.etapa or "Preparando")
            if t.etapa == "baixando modelo" and t.total:
                self.lbl_etapa.setText(
                    f"{nome}: {t.atual/1e6:.0f} de {t.total/1e6:.0f} MB")
            elif t.etapa == "baixando" and t.total:
                self.lbl_etapa.setText(
                    f"{nome}: {t.atual/1e6:.1f} de {t.total/1e6:.1f} MB")
            elif t.total:
                self.lbl_etapa.setText(f"{nome} — {t.atual} de {t.total}")
            else:
                self.lbl_etapa.setText(f"{nome}...")
            if t.total:
                self.barra_prog.setRange(0, t.total)
                self.barra_prog.setValue(min(t.atual, t.total))
            else:
                self.barra_prog.setRange(0, 0)
        if self.painel.t is t:
            self.painel.titulo.setText(t.titulo or os.path.basename(t.origem))
        self._atualizar_resumo()

    def _log(self, msg):
        # o log detalhado nao vai para a tela; fica no console para diagnostico
        print(msg, file=sys.stderr)

    def _acabou(self):
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.corredor = None
        self.btn_comecar.setEnabled(True)
        self.btn_cancelar.setEnabled(False)
        self.barra.setEnabled(True)
        self.barra_prog.setRange(0, 100)
        self.barra_prog.setValue(0)
        prontos = sum(1 for t in self.trabalhos if t.estado == fila.PRONTO)
        erros = sum(1 for t in self.trabalhos if t.estado == fila.ERRO)
        canc = sum(1 for t in self.trabalhos if t.estado == fila.CANCELADO)
        partes = [f"{prontos} pronto(s)"]
        if erros:
            partes.append(f"{erros} com erro")
        if canc:
            partes.append(f"{canc} cancelado(s)")
        self.lbl_etapa.setText("Fila encerrada — " + ", ".join(partes))
        self._reconstruir_lista()
        self._atualizar_resumo()
        if self.abas.currentIndex() == 1:
            self._encher_biblioteca()

    def closeEvent(self, e):
        if self.corredor:
            self.corredor.cancelar()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        self._fechar_resolvedor()
        e.accept()


# --------------------------------------------------------------------------

ESTILO = """
QMainWindow, QWidget { font-size: 13px; }
#coluna { background: palette(alternate-base); }
#barraEntrada { background: palette(alternate-base);
                border-bottom: 1px solid palette(mid); }
#barraEntrada[ativo="true"] { background: palette(highlight); }
#alvoSoltar { border: 1px dashed palette(mid); border-radius: 3px;
              padding: 6px 12px; color: palette(dark); }
#rotulo { font-size: 10px; font-weight: bold; letter-spacing: 1px;
          color: palette(dark); margin-top: 4px; }
#dica { color: palette(dark); font-size: 12px; }
#aviso { color: #b35900; font-size: 12px; }
#saida { font-family: Consolas, monospace; font-size: 11px;
         background: palette(alternate-base); border: 1px solid palette(mid);
         border-radius: 3px; padding: 8px; }
#etapa { border: 1px solid palette(mid); border-radius: 4px;
         background: palette(base); }
#etapa[desligado="true"] { background: palette(alternate-base); }
#numEtapa { background: palette(text); color: palette(base);
            border-radius: 13px; font-weight: bold; }
#etapa[desligado="true"] #numEtapa { background: palette(mid);
                                     color: palette(dark); }
QPushButton { padding: 6px 13px; border-radius: 3px;
              border: 1px solid palette(mid); background: palette(button); }
QPushButton:hover { border-color: palette(highlight); }
QPushButton:checked { background: palette(highlight);
                      color: palette(highlighted-text); }
QPushButton:disabled { color: palette(dark); }
QPushButton#primario { background: palette(text); color: palette(base);
                       border: none; font-weight: bold; }
QPushButton[classe="idioma"] { padding: 4px 10px; border-radius: 11px; }
QListWidget { border: none; background: transparent; }
QListWidget::item { padding: 7px 10px;
                    border-bottom: 1px solid palette(mid); }
QListWidget::item:selected { background: palette(highlight);
                             color: palette(highlighted-text); }
QProgressBar { border: 1px solid palette(mid); border-radius: 3px;
               background: palette(base); }
QProgressBar::chunk { background: palette(highlight); border-radius: 2px; }
QLineEdit { padding: 6px 9px; border: 1px solid palette(mid);
            border-radius: 3px; background: palette(base); }
QTabBar::tab { padding: 9px 16px; border: none;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom: 2px solid palette(text);
                        font-weight: bold; }
"""


# --------------------------------------------------------------------------

def _cli(argv):
    """Modo sem interface, para testar o exe empacotado de ponta a ponta."""
    import argparse
    p = argparse.ArgumentParser(prog="TranscritorBilingue --cli")
    p.add_argument("entrada", help="arquivo local ou link")
    p.add_argument("--idiomas", nargs="+", default=["en", "it"])
    p.add_argument("--modelo", default="large-v3")
    p.add_argument("--traduzir", nargs="*", default=[])
    p.add_argument("--formatos", nargs="+", default=["srt"])
    p.add_argument("--video", action="store_true")
    p.add_argument("--saida", default=None)
    a = p.parse_args(argv)

    base = a.saida or os.path.join(pasta_videos_padrao(), "cli")
    cfg = fila.Config(pasta_midia=base, pasta_legendas=base,
                      pasta_modelos=pasta_modelos_padrao(),
                      organizacao=fila.JUNTO)
    padrao = fila.Trabalho(origem="", idiomas=a.idiomas, modelo=a.modelo,
                           traduzir_ligado=bool(a.traduzir),
                           traduzir_para=list(a.traduzir),
                           formatos=a.formatos, baixar_video=a.video)
    e_url = a.entrada.startswith(("http://", "https://"))
    trabalhos = (fila.de_link(a.entrada, padrao, log=print) if e_url
                 else fila.de_arquivos([a.entrada], padrao))

    def mostrar(t):
        pct = f" {t.atual*100//t.total}%" if t.total else ""
        print(f"\r[{t.estado}] {t.titulo[:38]:38s} "
              f"{fila.ETAPAS.get(t.etapa, t.etapa)}{pct}   ",
              end="", flush=True)

    fila.Executor(cfg, ao_mudar=mostrar, ao_log=lambda m: None).rodar(trabalhos)
    print()
    for t in trabalhos:
        print(f"{t.estado}: {t.titulo}")
        for s in t.saidas:
            print(f"    {s}")
        if t.erro:
            print(f"    erro: {t.erro}")
    return 0 if all(t.estado == fila.PRONTO for t in trabalhos) else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        raise SystemExit(_cli(sys.argv[2:]))
    app = QApplication(sys.argv)
    app.setApplicationName("Transcritor Bilingue")
    j = Janela()
    j.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
