# Transcritor Bilíngue

App desktop Windows, em duas máquinas: uma com GPU NVIDIA (GTX 1650), outra
só com vídeo integrado (roda no caminho de CPU — hoje sem teste dedicado).
A segunda máquina não instala Python: recebe o `.exe` do instalador pronto.

O projeto é maior do que "transcritor de filme bilíngue" sugere. Seis peças:

1. **Baixador em massa** (`baixar.py`) — YouTube via yt-dlp, playlists inclusas.
2. **Fila / esteira** (`fila.py`) — enfileira, baixa, transcreve, traduz.
3. **Transcritor com idioma por trecho** (`motor.py`) — o núcleo: VAD →
   identificação de idioma por trecho → transcrição travada por trecho →
   filtro de alucinação. Não trava um idioma só no arquivo inteiro (diferença
   pro CapCut/TurboScribe). Caso de uso original: Stromboli (1950), inglês e
   italiano alternando dezenas de vezes.
4. **Tradutor** (`traduzir.py`) — NLLB-200 via ctranslate2.
5. **Legendador** (`legendar.py`) — formata o `.srt`.
6. **Interface** (`app.py`) — PySide6, fila visual, e o instalador (Inno
   Setup) como parte do produto entregue, não só ferramenta de dev.

Ver `README.md` para uso e detalhes técnicos (pipeline, empacotamento).

**Handoff:** `HANDOFF.md` é a referência de contexto de sessão (estado
atual, pendências, decisões recentes). `README.md` é a documentação do
app (uso, pipeline técnico, build/empacotamento). Atualizar cada um só
quando o Samuel pedir explicitamente.

Decisões fechadas: Python + PySide6 (não sugerir alternativa); Windows só;
UI e comentários em pt-BR; não empacotar os pesos do modelo (baixam na 1ª
execução); usuário é leigo; `--onedir` no PyInstaller, não `--onefile`.

## Como trabalhar com o Samuel

- Ele está aprendendo a programar. Explicar em português, primeiro a frase
  que se entende, depois o termo técnico.
- **Uma mudança por vez.** Antes de alterar um arquivo, mostrar o diff e
  esperar confirmação.
- **Não recomeçar do zero nem reescrever o que funciona.** Organizar não é
  permissão para reconstruir.
- Em decisão técnica, sinalizar o ponto de escolha e oferecer 2–3 opções
  com prós/contras e uma recomendação. Quem decide é o Samuel.
- **Prova visual antes de declarar "feito".** Ao fim de cada etapa, dizer o
  comando exato que ele roda para conferir e o que deve aparecer na tela.
  Só ele marca CONFERIDO (ver `PEDIDOS.md`, se existir).
- Ser conciso e honesto. Avisar se ele estiver enganado ou correndo risco.

## Commit e push regulares

Este repositório tem GitHub remoto (`origin`). Faça commit do progresso
relevante regularmente e dê `git push` — não é preciso perguntar cada vez,
mas sempre revise o que está sendo commitado antes (nunca commitar segredo;
`.venv/`, `build/`, `dist/`, `release/`, `installer_output/` e `modelos/`
já ficam fora pelo `.gitignore`).
