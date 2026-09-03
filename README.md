# Transcritor Bilíngue

Transcreve filmes e áudios que **trocam de idioma no meio** (code-switching),
decidindo o idioma **trecho por trecho** — não trava um idioma no arquivo
inteiro como CapCut ou TurboScribe. Gera legenda `.srt` e um relatório dos
trechos descartados.

Caso de uso original: um filme de 1950 em que uma personagem fala inglês e os
outros respondem em italiano, alternando dezenas de vezes.

---

## Como usar (usuário final)

1. Abra o **Transcritor Bilíngue** pelo menu Iniciar.
2. Arraste o vídeo ou áudio para a área grande (ou clique em *Procurar*).
3. Marque os idiomas que aparecem no filme (Inglês e Italiano já vêm marcados).
4. Escolha a qualidade:
   - **Grande** — melhor qualidade, usa a placa de vídeo.
   - **Médio** — mais rápido, funciona em qualquer PC.
   - **Pequeno** — rascunho rápido, menos preciso.
5. Clique em **Transcrever**. Acompanhe a barra de progresso (dá para cancelar).
6. Ao terminar, use **Abrir a pasta do resultado**. A legenda `.srt` fica na
   mesma pasta do vídeo.

A janela nunca congela: o trabalho roda numa thread separada.

### Primeira execução: download do modelo

O programa **não** vem com o modelo de transcrição embutido (o "Grande" passa
de 3 GB). Na primeira vez que você escolhe um modelo, ele é baixado uma única
vez para `%LOCALAPPDATA%\TranscritorBilingue\modelos`. Depois disso funciona
sem internet.

- Se o download for interrompido, ele **retoma** de onde parou.
- Se **não houver internet** na primeira vez, o programa avisa claramente que
  precisa baixar o modelo uma vez.

### Placa de vídeo (GPU)

- Com uma placa **NVIDIA** compatível, a transcrição usa a GPU e fica rápida.
  As bibliotecas CUDA necessárias (cuBLAS/cudart) já vêm no programa.
- **Sem** placa compatível, roda na CPU — o programa avisa **antes** de começar
  que pode levar horas, com uma estimativa baseada na duração do arquivo.

### Saídas

- `nome_do_filme.srt` — legenda com marcações de tempo. Se você marcar a opção,
  cada linha vem com prefixo `[EN]` / `[IT]`.
- `nome_do_filme_relatorio.json` — relatório com os trechos **descartados** e o
  motivo (repetição em loop, sem fala, confiança baixa, alfabeto inesperado),
  além dos aceitos. A tela final também lista os descartados com horário,
  motivo e confiança, para você saber onde não confiar.

---

## ⚠️ Aviso do Windows SmartScreen

O executável **não é assinado digitalmente** (assinatura custa caro e exige
certificado). Por isso, ao abrir o instalador ou o programa pela primeira vez,
o Windows pode mostrar uma tela azul do **SmartScreen** dizendo algo como
*"O Windows protegeu o computador"*.

Isso é esperado e **não** significa vírus. Para continuar:

1. Clique em **Mais informações**.
2. Clique em **Executar assim mesmo**.

---

## Como o motor evita os erros clássicos de transcrição

O pipeline tem quatro camadas, nesta ordem:

1. **VAD antes de tudo** — fatia o áudio em trechos de fala e nunca manda
   silêncio, música ou ruído para o modelo. (Evita legenda em cima de erupção
   vulcânica, mar e trilha sonora.)
2. **Identificação de idioma por trecho, com conjunto fechado** — o
   classificador só pode responder dentro dos idiomas que você marcou. É isso
   que impede a saída virar tâmil, coreano ou devanágari.
3. **Transcrição com o idioma travado por trecho** e
   `condition_on_previous_text=False` — sem realimentar o texto anterior, que é
   a causa dos loops "Salamat Salamat Salamat...".
4. **Filtro de saída** — descarta log-prob baixo, `no_speech_prob` alto,
   repetição em loop e alfabeto inesperado. Nada some calado: o descartado vai
   para o relatório com o motivo.

Trecho abaixo de ~1,2 s tem detecção pouco confiável e **herda o idioma do
vizinho** em vez de decidir sozinho.

### Limitação conhecida: dialeto siciliano

O filme tem trechos em **siciliano**. Nenhum modelo dessa família tem
siciliano, então esses trechos são classificados como italiano e o modelo
inventa italiano padrão por cima. Isso **não tem conserto** aqui. O que o
programa faz é marcar esses trechos com **confiança baixa** no relatório, para
você saber onde revisar.

---

## Para desenvolvedores (build)

Requisitos: Windows 64 bits, Python 3.14 (o projeto foi construído e testado
no 3.14.3), placa NVIDIA opcional para GPU.

```powershell
# ambiente
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install faster-whisper PySide6 pyinstaller `
    yt-dlp tokenizers edge-tts soundfile numpy `
    nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12

# testes que não precisam de GUI nem de rede
.\.venv\Scripts\python test_filtro.py     # filtro de alucinação
.\.venv\Scripts\python test_legendar.py   # formatação da legenda
.\.venv\Scripts\python test_fila.py       # fila, nomes e pastas

# testes que precisam do modelo baixado
.\.venv\Scripts\python test_traduzir.py   # tradução NLLB
.\.venv\Scripts\python validate_motor.py  # lang-id ponta a ponta

# rodar a interface em desenvolvimento
.\.venv\Scripts\python app.py

# empacotar (onedir) e gerar o instalador
.\.venv\Scripts\python -m PyInstaller transcritor.spec --noconfirm
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" instalador.iss
# instalador em: installer_output\TranscritorBilingue-Instalador.exe
```

O `.iss` lê direto de `dist\`, que é onde o PyInstaller grava. Não há passo de
cópia manual — antes havia, e era fácil empacotar a build anterior sem notar.

### Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | Interface PySide6 (também tem modo `--cli` para testes) |
| `fila.py` | Fila de trabalhos e a esteira baixar → transcrever → traduzir |
| `baixar.py` | YouTube via yt-dlp: resolve link/playlist e baixa áudio ou vídeo |
| `motor.py` | Pipeline: VAD → lang-id → transcrição → filtro de alucinação |
| `traduzir.py` | Tradução com NLLB-200 em ctranslate2 (sem torch) |
| `legendar.py` | Formatação: divide, quebra em 2 linhas, folga entre legendas |
| `download_modelo.py` | Download dos modelos na 1ª execução (progresso + retomada) |
| `cuda_setup.py` | Registra as DLLs CUDA para a GPU funcionar |
| `transcritor.spec` | Receita do PyInstaller (binários nativos, Qt, CUDA, yt-dlp) |
| `instalador.iss` | Script do Inno Setup (instalação por usuário, sem admin) |

### Notas de empacotamento

- **`--onedir`, não `--onefile`**: onefile extrai tudo para o `%TEMP%` a cada
  abertura, o que num app deste tamanho vira meio minuto de espera.
- Binários nativos declarados à mão no `.spec`: `ctranslate2`, `onnxruntime`,
  `av`/ffmpeg e o `silero_vad_v6.onnx`.
- **CUDA**: só as DLLs mínimas são empacotadas (`cublas64_12`, `cublasLt64_12`,
  `cudart64_12`, ~740 MB) em `_internal/nvidia_bin`. O cuDNN e o OpenMP já vêm
  dentro do `ctranslate2`, então **não** são reempacotados (economiza ~1,5 GB).
- **Qt**: só `QtCore/QtGui/QtWidgets`. Módulos pesados (WebEngine, Quick,
  Designer, etc.) ficam de fora pela lista `excludes` do `.spec`. O plugin de
  plataforma `qwindows.dll` é incluído (sem ele o app fecha na abertura com
  "could not find or load the Qt platform plugin windows").
- **Pesos do modelo não são empacotados** — baixados na primeira execução.
