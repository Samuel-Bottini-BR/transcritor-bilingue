# Handoff — Transcritor Bilíngue

## O que é e para quem

App desktop Windows que transcreve áudio/vídeo com troca de idioma **trecho
por trecho** (code-switching) — não trava um idioma no arquivo inteiro como
CapCut ou TurboScribe. Usuário final leigo (o Samuel usa diretamente;
interface e comentários em pt-BR, sem jargão). Rodará em **duas máquinas**:
esta (GPU NVIDIA GTX 1650) e outra só com vídeo integrado, sem NVIDIA — essa
segunda não instala Python, recebe o `.exe` do instalador pronto, e o
caminho de CPU do motor **ainda não tem teste dedicado** (risco conhecido,
ver "O que falta").

O projeto é maior do que "transcritor de filme bilíngue" sugere — são seis
peças (baixador em massa, fila/esteira, motor de transcrição por trecho,
tradutor NLLB, legendador, interface+instalador). Descrição completa de cada
peça está no `CLAUDE.md`. Ver `README.md` para uso e pipeline técnico.

## Estado atual (2026-09-07)

**Em andamento — plano de boas práticas (`PROMPT-boas-praticas.md`, colado
pelo Samuel, não é um arquivo do repo).** O plano tem 6 fases, uma mudança
por vez, com aprovação explícita do Samuel a cada etapa ("só ele marca
CONFERIDO"). Progresso:

- ✅ **Fase 1 — `requirements.txt`**: criado pelo Samuel antes desta sessão
  (versões travadas do `.venv`, em blocos: núcleo / GPU / empacotamento /
  teste; declara `av` e `huggingface_hub`, que antes entravam só por tabela).
  Prova rodada e confirmada: `pip install -r requirements.txt` não baixa
  nada, só "Requirement already satisfied". Commitado (`390bf05`).
- 🔶 **Fase 2 — `CLAUDE.md`/`README.md` refletindo o projeto real**:
  **escrita e commitada (`3d1195a`) como rascunho, mas o Samuel AINDA NÃO
  confirmou** ("confere?" foi perguntado, sem resposta ainda quando este
  checkpoint foi salvo). `CLAUDE.md` ganhou a descrição das 6 peças, as duas
  máquinas-alvo, e a seção "Como trabalhar com o Samuel" (regras de sessão:
  uma mudança por vez, mostrar diff antes de escrever, prova visual ao fim
  de cada etapa, só ele marca CONFERIDO). `README.md` só teve o comando de
  instalação trocado pra apontar ao `requirements.txt`.
- ⬜ **Fases 3 a 6 — não começadas.** Resumo de cada uma (o plano completo
  original não está salvo em lugar nenhum além daqui, então esta é a
  referência):
  - **Fase 3 (organizar pastas/git):** criar `testes/` e mover pra lá
    `test_filtro.py`, `test_legendar.py`, `test_fila.py`, `test_traduzir.py`,
    `validate_motor.py` e os materiais (`teste_bilingue.wav`/`.srt`/
    `_relatorio.json`/`_verdade.txt`). Propor ao Samuel mover
    `bench.py`/`bench2.py`/`bench3.py`/`gerar_audio_teste.py` pra
    `ferramentas/` ou apagar os benchmarks (ele decide). **Não mover os
    módulos do app** (`app.py`, `motor.py`, `fila.py`, `baixar.py`,
    `traduzir.py`, `legendar.py`, `download_modelo.py`, `cuda_setup.py`) —
    mexeria no `transcritor.spec` do PyInstaller sem ganho. Parar de
    versionar `teste_bilingue.srt`/`teste_bilingue_relatorio.json` (são
    saída dos testes) — mas checar antes se `teste_bilingue_verdade.txt` é
    entrada, não saída. Decidir com o Samuel o destino de
    `_extras-area-de-trabalho/` (gitignore ou sai da pasta do projeto).
    Prova: `python app.py` abre; os 3 testes sem GUI passam; `git status`
    fica limpo depois.
  - **Fase 4 (comando único de teste):** ponto de escolha a apresentar ao
    Samuel — `pytest` (padrão, exige adaptar os testes que hoje são scripts
    com `print`) vs. um script simples que só chama os testes como estão
    (zero reescrita). Não decidido ainda.
  - **Fase 5 (testar peças frágeis):** teste de `baixar.py` **sem acessar
    a internet** (nomes de arquivo, pastas, formato, playlist). Teste de
    fumaça do **caminho de CPU** (modelo pequeno, forçado, sobre
    `teste_bilingue.wav`) — importante porque a segunda máquina não tem GPU.
  - **Fase 6 (`PEDIDOS.md` + git por branch):** criar `PEDIDOS.md` com
    estados pendente/feito/conferido (só o Samuel marca conferido). Passar a
    usar uma branch por mudança em vez de commitar direto no `master`.

**O que NÃO fazer neste plano** (regra explícita do Samuel): não mexer em
`app.py` além do necessário pras fases; não trocar bibliotecas nem sugerir
alternativa ao PySide6; não reescrever `motor.py`/`fila.py`/`traduzir.py`
(funcionam); não rodar a transcrição do arquivo de 4h50 (não é o objetivo
agora, seria só pra validar a GUI — ver item separado abaixo).

**Migração de disco (sessão anterior, já concluída e validada):** o
projeto foi movido de `C:\Users\fotog\transcritor-bilingue` para
`D:\programas\transcritor-bilingue` (HD externo). Cópia antiga em C: já
apagada. `.venv` recriado do zero em D: (não é portável entre unidades).
`_extras-area-de-trabalho/` (testes do Stromboli original + protótipo
`transcritor_bilingue.py` anterior à divisão em módulos) preservado na
pasta nova, fora do git.

**Bug corrigido (sessão anterior, commitado):** painel de idiomas tinha um
padrão fixo (Inglês+Italiano) que ignorava a escolha do usuário se feita
antes do item aparecer na fila. Corrigido em `app.py`
(`PainelTrabalho.mostrar`/`_recolher_mesmo` + `MainWindow`). Commit
`7e3a1f5`.

## Descobertas de comportamento real

- **Processos em segundo plano do Claude têm limite de tempo curto** e são
  encerrados no meio de tarefas longas (testado com a transcrição real de
  ~4h50 — chegou a rodar identificação de idioma 100% + começo da
  transcrição, mas foi encerrada por esse limite, não por bug do app). Para
  qualquer teste que precise rodar mais que poucos minutos, a validação tem
  que ser feita pelo próprio Samuel, direto no terminal dele.
- GPU (GTX 1650) confirmada funcional via `motor.gpu_disponivel()` no
  `.venv` novo de D:. Estimativa de tempo pra esse arquivo de teste (~4h50,
  qualidade Grande): ~1h com GPU.
- `git`, incluindo histórico completo, sobrevive normalmente a uma cópia de
  pasta via `robocopy` (usado pra migrar C:→D:) — não precisou de
  `git clone` nem re-init.

## Perguntas em aberto

**Pergunta exata pendente:** "O `CLAUDE.md` e `README.md` da Fase 2 [ver
diff nos commits `3d1195a`] descrevem corretamente o projeto do Samuel?" —
perguntei e ainda não obtive um "sim"/"confere"/"CONFERIDO" explícito antes
deste checkpoint. **Não seguir pra Fase 3 sem essa confirmação.**

## Próximo passo recomendado

Perguntar ao Samuel se ele já confirmou a Fase 2 (releia o `CLAUDE.md` e o
`README.md` atuais primeiro — pode ter mudado). Se sim, seguir pra Fase 3
(organizar pastas), uma mudança por vez, sempre mostrando diff antes de
escrever.

## Como rodar / testar

```powershell
cd "D:\programas\transcritor-bilingue"

# confirma que as dependencias batem com requirements.txt (deve so dizer
# "already satisfied", sem baixar nada)
.\.venv\Scripts\python -m pip install -r requirements.txt

# testes sem GUI nem rede (rodados nesta sessao, todos passando)
.\.venv\Scripts\python test_filtro.py
.\.venv\Scripts\python test_legendar.py
.\.venv\Scripts\python test_fila.py

# abrir o app
.\.venv\Scripts\python app.py
```

## Ambiente

- Python 3.14 (`.venv` recriado em D: numa sessão anterior).
- Dependências agora travadas em `requirements.txt` (não instalar pacotes
  soltos — sempre por esse arquivo). Versões-chave: `faster-whisper==1.2.1`,
  `PySide6==6.11.2`, `ctranslate2==4.8.2`, `yt-dlp==2026.8.19`.
- GPU NVIDIA (GTX 1650) disponível nesta máquina; a outra máquina-alvo não
  tem NVIDIA (caminho CPU do motor, ver "O que falta" na Fase 5).

Ver `README.md` para o passo a passo completo de build/empacotamento e a
lista de arquivos do projeto.
