# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.6 concluída localmente](docs/tasks/active/F4.6.md): contrato, implementação e aceite preservados.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.5 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.6 — detectar stack e resolver comandos efetivos no worktree |
| **Gate** | `REPAIR_ACTIVE / PROMOTION_BLOCKED`; checkpoints locais `checkpoint/f4.6-ready`, `checkpoint/f4.6-r1-ready`, `checkpoint/f4.6-complete` e `checkpoint/f4.6-r2-ready` |
| **Executor ativo** | `Codex`, único escritor; autorização nominal em `2026-08-11T02:00:32-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.6-detect-stack-commands`, local, sem upstream |
| **Baseline promovido** | `main == origin/main == 46b70709b773a6bca0aa7adfd76d40b3cdf27e23` |
| **CI do baseline** | run `31459891130`, evento `push`, 11/11 verde, inclusive `CI required` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

A F4.5 foi incorporada pelo PR #42 no merge `4ae0de798607cf4fec13c0469fddb93d8024ead5`,
com CI pós-merge `31458482033` 11/11. Sua reconciliação administrativa PR #43 foi incorporada no
merge `46b70709b773a6bca0aa7adfd76d40b3cdf27e23`; a execução de `push` `31459891130` terminou
11/11 verde. As branches foram preservadas; nenhuma tag remota foi publicada nem ref excluída.
O histórico `POST_PROMOTION_BLOCKED` da F4.1 permanece encerrado pela corretiva F4.C1.

## 5. Tarefa ativa

O `VerificationEngine` agora exige `ProvisionedWorktree`, detecta a stack pela configuração real,
resolve a suíte inteira em contratos imutáveis de `argv`/cwd/executável/fonte e valida todos os
pré-requisitos antes do primeiro subprocesso. Configuração ausente, ambígua ou inválida, stack não
suportada e ferramenta/módulo indisponível produzem `VerificationPrerequisiteError` com código
`ERROR_PREREQUISITE`. O runner usa o `PathGuard` do worktree e o terminal tipado promovido.

O PR #44 foi aberto no head `f258541`, mas a CI `31463009231` reabriu o gate: os jobs Tests Ubuntu
3.11/3.14 executaram o Python base em vez do launcher `.venv/bin/python` e falharam com
`No module named pytest`. A causa é a dereferência do symlink por `Path.resolve()` no resolver.

Persistência de resultado, status/tempo/exit/output/digest, guard de `COMPLETED`, correção decisória da
CLI e integração ao lifecycle pertencem à F4.7. Repair/retry pertence à F4.8; F3.7 permanece depois da
F4.7. Essas fronteiras não podem ser antecipadas.

## 6. Evidência de conclusão local

- implementação: `507c216`; recongelamento ambiental: `a4081b2`;
- aceite focado: 35 testes; worktree/terminal/guard: 51; compatibilidade F4: 109;
- regressão R1 integral e isolada: `735 passed, 2 skipped, 6 subtests passed`;
- documentação, ledger e UTF-8 finais: `25 passed, 6 subtests passed`;
- mypy Windows/Linux: 106 arquivos, zero issues; Ruff, compileall e `git diff --check`: verdes;
- build isolado de sdist/wheel e smoke da wheel: verdes; `uv 0.12.3` foi instalado somente no venv
  temporário do smoke, sem instalação global ou mudança no projeto;
- escopo proibido permaneceu byte-idêntico e o workspace terminou limpo.

O reparo R2 está limitado a preservar o launcher do venv e cobrir a regressão POSIX. Merge, tag
remota, exclusão de ref, force-push, bypass, F4.7, F4.8 e F3.7 não estão autorizados. A evidência
negativa bloqueia promoção até correção e recertificação integral.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
CRIAR O CHECKPOINT LOCAL checkpoint/f4.6-r2-ready; REPARAR SOMENTE A PRESERVAÇÃO DO LAUNCHER
sys.executable EM POSIX; RECERTIFICAR O ACEITE INTEGRAL E ATUALIZAR O PR #44. NÃO PUBLICAR TAG,
MESCLAR PR, EXCLUIR REF, ALTERAR PROTEÇÃO OU INICIAR F4.7/F4.8/F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.6.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e a DEC-015.
3. Confirme branch, status, checkpoints, PR #44/run `31463009231`, baseline e runtime.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T02:51:00-03:00 | Fonte: PR #44/run `31463009231` + gate R2 F4.6*
