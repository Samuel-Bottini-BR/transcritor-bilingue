# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller (--onedir) para o Transcritor Bilingue.

Declara a mao os binarios/dados que o PyInstaller nao acha sozinho:
  - ctranslate2, onnxruntime, av (ffmpeg) -> DLLs nativas
  - faster_whisper/assets/silero_vad_v6.onnx -> modelo do VAD
  - yt_dlp -> os extratores sao carregados por nome em runtime, entao o
    PyInstaller nao os descobre sozinho e o download quebraria no app pronto
  - tokenizers -> usado pelo NLLB (traducao) sem passar por transformers
  - DLLs CUDA minimas (cublas + cudart) para a GPU, em _internal/nvidia_bin

NAO empacota pesos de modelo: nem o Whisper (ate 3,1 GB) nem o NLLB (647 MB).
Os dois sao baixados na primeira execucao pelo download_modelo.py.
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

# pacotes com binarios/dados nativos: pega tudo (datas + binaries + submodulos)
for pkg in ["faster_whisper", "ctranslate2", "onnxruntime", "av",
            "tokenizers", "huggingface_hub", "yt_dlp"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# certificados para o download do modelo na primeira execucao
datas += collect_data_files("certifi")

# DLLs CUDA minimas para a GPU (o cuDNN e o OpenMP ja vem no ctranslate2).
# Vao para _internal/nvidia_bin; o cuda_setup registra essa pasta em runtime.
import nvidia
_nv = list(nvidia.__path__)[0]
for rel in [("cublas", "cublas64_12.dll"),
            ("cublas", "cublasLt64_12.dll"),
            ("cuda_runtime", "cudart64_12.dll")]:
    p = os.path.join(_nv, rel[0], "bin", rel[1])
    if os.path.isfile(p):
        binaries.append((p, "nvidia_bin"))

# modulos proprios. cuda_setup entra aqui porque e importado so pelo efeito
# colateral (registrar as DLLs do CUDA), e os demais para garantir que a
# esteira inteira va junto mesmo se algum import virar condicional.
hiddenimports += ["cuda_setup", "motor", "download_modelo",
                  "baixar", "traduzir", "legendar", "fila"]

# Qt: so usamos QtCore/QtGui/QtWidgets. Exclui os modulos pesados para nao
# inchar o pacote com WebEngine, Quick, Designer, etc.
excludes = [
    "edge_tts", "soundfile", "matplotlib", "tkinter", "pytest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtDesigner",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtSvgWidgets",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="TranscritorBilingue",
    debug=False,
    strip=False,
    upx=False,
    console=False,         # app de janela: sem console (headless via --cli ainda funciona)
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="TranscritorBilingue",
)
