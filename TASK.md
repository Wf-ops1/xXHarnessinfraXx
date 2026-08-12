# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F3.7](docs/tasks/active/F3.7.md): único dossiê ativo e contrato da promoção Git segura.
3. [F4.8](docs/tasks/completed/F4.8.md): última tarefa promovida e reconciliada.
4. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e tarefa F3.7.
5. [DEC-013](docs/decisions/DEC-013-fase3-ordem-operacional.md),
   [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md).
6. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.8 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 3 — fechamento da promoção Git segura após gates F4 promovidos |
| **Tarefa ativa** | F3.7 — promoção Git segura |
| **Gate** | F3.7 R2 `REPAIR_ACTIVE / PROMOTION_BLOCKED`; CI R1 falhou nos E2E Ubuntu do head `5c80162` |
| **Executor ativo** | `Codex`, único escritor; autorizado em `2026-08-12T00:48:45-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f3.7-safe-promotion`, rastreando `origin/task/f3.7-safe-promotion`, criada de `9f75e35db38fc6648497c01bd8f81dcdecec8029` |
| **Main atual** | `main == origin/main == 9f75e35db38fc6648497c01bd8f81dcdecec8029` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **Checkpoint READY** | `checkpoint/f3.7-ready` → commit documental deste gate |
| **Produto local** | `cb80f8b2d86b9ff38075e6f0068e32b62ba4dbb5` — produto intacto; certificação reaberta por falha de teste |
| **Checkpoint de conclusão inicial** | `checkpoint/f3.7-complete` → `ac1d3e2`, somente local |
| **Reparo R1** | `d31227694344ea89303bfb6853eb238c4ca6d8f7` — prova direta do cherry-pick, produto inalterado |
| **Checkpoint R1** | `checkpoint/f3.7-r1-ready` → `6333217`; `checkpoint/f3.7-r1-complete` → recertificação final, somente locais |
| **Checkpoint R2** | `checkpoint/f3.7-r2-ready` → próximo commit documental; somente local |
| **Pull request** | [#51](https://github.com/Wf-ops1/Harnessinfra/pull/51), não-draft contra `main`; head falho `5c80162` |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F4.8 — repair loop orientado pelos gates |
| Produto | [PR #49](https://github.com/Wf-ops1/Harnessinfra/pull/49), head `f9c8c2d`; merge `72f89e3`; pós-merge `31551685950`, 11/11 |
| Reconciliação | [PR #50](https://github.com/Wf-ops1/Harnessinfra/pull/50), head `a15b918`; run `31554671587`, 11/11 |
| Fechamento administrativo | merge `9f75e35db38fc6648497c01bd8f81dcdecec8029`; run pós-merge `31557794240`, 11/11 |
| Estado | F4.8 `PROMOTED / RECONCILED / CLOSED`; PR administrativo não gera reconciliação recursiva |
| Fronteira | branches remotas preservadas; checkpoints F4.8 somente locais; nenhuma tag publicada |

Nenhuma evidência negativa posterior foi observada. A F3.7 começou somente após esse fechamento e
autorização nominal separada.

## 5. Tarefa ativa

O baseline F3.7 comprovou SHA sintético, `git add .` no checkout configurado e fallback positivo. O
produto local substituiu esse caminho por candidate commit real e singular no worktree F3.6,
referência durável, composição opt-in no lifecycle, suíte full vinculada ao candidate SHA, aprovação
canônica e promoção exclusivamente por `git cherry-pick <candidate_sha>`.

O checkout original é revalidado imediatamente antes do efeito. Base divergente termina em
`BLOCKED_BASE_CHANGED`; dry-run preserva o checkout e termina em `DRY_RUN_COMPLETED`; write-ahead,
outcome e recovery impedem repetição cega após interrupção. Sem injeção F3.7, a semântica promovida
F4.7/F4.8 permanece compatível.

Certificação observada: gate focado `74 passed`; regressão integral única `774 passed, 5 skipped,
6 subtests passed`; mypy em 106 arquivos, Ruff, compileall, build PEP 517 e smoke oficial offline da
wheel verdes. O smoke carregou `ai-engineering-harness 0.1.0` de origem externa ao checkout.

## 6. Bloqueios atuais

O R1 corrigiu a assertion unitária e passou localmente `10/10`, gate focado `74`, regressão integral
`774 passed, 5 skipped, 6 subtests passed`, mypy/Ruff/compileall, build e smoke. No run
[31567250425](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31567250425), a suíte unitária
Ubuntu ficou verde (`749/1/6`), mas duas assertions equivalentes remanesceram no E2E: Python 3.11
falhou `2/26/1`, Python 3.14 falhou `1/27/1`, e `CI required` agregou failure. Os oito outros jobs
passaram. Produto e `src/` permanecem intactos; R2 limita-se aos E2E e estado documental.

Tag remota, exclusão de ref e início de outra tarefa não estão autorizados.

## 7. Próxima ação exata

```text
CRIAR CHECKPOINT F3.7-R2-READY, REPARAR AS DUAS ASSERTIONS E2E E REPETIR TODO O ACEITE.
PUBLICAR O R2 E MESCLAR SOMENTE APÓS 11/11 VERDES NO SHA EXATO.
NÃO PUBLICAR TAG, EXCLUIR REF OU INICIAR OUTRA TAREFA.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F3.7.md` integralmente.
2. Leia as seções 1.1–1.2 e F3.7 do plano, além das DEC-013/014/015.
3. Confirme branch `task/f3.7-safe-promotion`, baseline/main `9f75e35`, CI pós-merge
   `31557794240`, workspace limpo e Python 3.12.13.
4. Confirme `checkpoint/f3.7-ready == f84af68`, gate focado 74, regressão integral 774/5/6 e
   build/smoke verdes antes de criar ou validar `checkpoint/f3.7-complete`.

---

*Atualizado em: 2026-08-12T02:44:52-03:00 | Fonte: F3.7 R2 + PR #51 + CI 31567250425 + R1 d312276/774/5/6 + F3.6 + F4.7/F4.8 + DEC-013/014/015*
