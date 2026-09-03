# Transcritor Bilíngue

App desktop Windows que transcreve áudio/vídeo com troca de idioma **trecho
por trecho** (code-switching) — não trava um idioma no arquivo inteiro como
CapCut ou TurboScribe. Caso de uso original: um filme de 1950 (Stromboli)
com inglês e italiano alternando dezenas de vezes. Ver `README.md` para uso
e detalhes técnicos (pipeline, empacotamento, decisões fechadas).

**Handoff:** `README.md` é a referência principal — não há um handoff
separado ainda. Se este projeto crescer, considerar um `HANDOFF.md`
próprio; até lá, atualizar o README quando o Samuel pedir explicitamente.

Decisões fechadas: Python + PySide6 (não sugerir alternativa); Windows só;
UI e comentários em pt-BR; não empacotar os pesos do modelo (baixam na 1ª
execução); usuário é leigo.

## Commit e push regulares

Este repositório tem GitHub remoto (`origin`). Faça commit do progresso
relevante regularmente e dê `git push` — não é preciso perguntar cada vez,
mas sempre revise o que está sendo commitado antes (nunca commitar segredo;
`.venv/`, `build/`, `dist/`, `release/`, `installer_output/` e `modelos/`
já ficam fora pelo `.gitignore`).
