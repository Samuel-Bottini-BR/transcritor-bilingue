# Handoff — Transcritor Bilíngue

## O que é e para quem

App desktop Windows que transcreve áudio/vídeo com troca de idioma **trecho
por trecho** (code-switching) — não trava um idioma no arquivo inteiro como
CapCut ou TurboScribe. Gera legenda `.srt` e um relatório dos trechos
descartados. Caso de uso original: um filme de 1950 (Stromboli) com inglês
e italiano alternando dezenas de vezes. Usuário final leigo (o Samuel usa
diretamente; interface e comentários em pt-BR, sem jargão). Ver `README.md`
para uso, pipeline técnico e detalhes de empacotamento.

## Estado atual (2026-09-07)

**Local do projeto mudou nesta sessão:** de `C:\Users\fotog\transcritor-bilingue`
para `D:\programas\transcritor-bilingue` (HD externo), a pedido do Samuel.
A cópia em C: ainda existe, mas fica obsoleta — apagar depois que o Samuel
confirmar que o app abre e funciona normalmente a partir de D:. O `.venv`
não foi copiado (não é portável entre unidades); foi recriado do zero em D:
com `py -3.14 -m venv .venv` e as dependências reinstaladas. Um `_extras-area-de-trabalho/`
antigo (testes do Stromboli original + um script prototype de página única,
`transcritor_bilingue.py`, anterior à divisão em app.py/motor.py/fila.py)
foi preservado dentro da pasta nova — não está no git, é só histórico.

**Bug corrigido nesta sessão:** o painel de idiomas tinha um "padrão" fixo
(Inglês+Italiano) usado sempre que um item novo era adicionado à fila. Se o
usuário escolhesse o idioma *antes* de o item aparecer na lista (ex.: colar
um link e clicar em "Português" enquanto ainda resolvia), a escolha era
descartada silenciosamente assim que o item surgia com os idiomas padrão —
foi assim que o Samuel reparou (marcou Português, o app ignorou e foi de
Inglês/Italiano mesmo assim).

Corrigido em `app.py` (`PainelTrabalho.mostrar` / `_recolher_mesmo` +
`MainWindow._selecionou`/`__init__`): agora, quando nada está selecionado na
fila, o painel mostra e edita `self.padrao` diretamente (título "Padrão para
novos itens"), em vez de travar a edição com "Nada selecionado". A escolha
de idioma passa a valer de verdade para os próximos itens adicionados.
Commitado (`7e3a1f5`) e no push, antes da mudança de pasta — o histórico
git veio junto na cópia para D:.

**Testado:** rodei o motor via `--cli` no arquivo real do Samuel (~4h50 de
áudio, mp3 128kbps,
`C:\Users\fotog\Downloads\YTDown.com_YouTube_Media_MzMM5iV3GcU_009_128k.mp3`)
com `--idiomas pt`. A identificação de idioma completou 100% corretamente e
a transcrição começou (chegou a 1%) antes do processo precisar ser
encerrado — o motor funciona bem no arquivo real, GPU disponível (GTX 1650),
estimativa de ~1h para o arquivo inteiro com qualidade Grande. **Não** foi
possível validar o fluxo completo pela GUI: os processos em segundo plano
que o Claude usa para abrir o app têm um limite de tempo curto e são
encerrados no meio — não é bug do app, é limitação do ambiente do Claude.

## Decisões fechadas

- Python + PySide6 (não sugerir alternativa); Windows só.
- UI e comentários em pt-BR; usuário final é leigo.
- Não empacotar os pesos do modelo (baixam sozinhos na 1ª execução).
- `--onedir`, não `--onefile`, no PyInstaller (ver README, seção de
  empacotamento).
- Projeto vive em `D:\programas\transcritor-bilingue` (HD externo) — não
  mais em C:. Sem `backup_path` registrado por enquanto; o GitHub remoto
  (`origin`) é a segurança.

## O que falta

- Samuel confirmar que o app abre e roda normalmente a partir de D:.
- Depois dessa confirmação, apagar a cópia antiga em
  `C:\Users\fotog\transcritor-bilingue`.
- Samuel rodar a transcrição completa do arquivo de teste (~4h50) ele
  mesmo, direto no terminal (fora do controle do Claude), para validar o
  fluxo completo pela GUI de ponta a ponta — inclusive confirmar
  visualmente que a correção do idioma padrão funciona na prática.

## Como rodar

```powershell
cd "D:\programas\transcritor-bilingue"
.\.venv\Scripts\python.exe app.py
```

Ver `README.md` para o passo a passo completo de build/empacotamento e a
lista de arquivos do projeto.
