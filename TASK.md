# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.7](docs/tasks/active/F4.7.md): único dossiê ativo, contrato, aceite e rollback congelados.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.6 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.7 — persistência e guard canônico dos resultados de verificação |
| **Gate** | F4.7-R1 `READY / POST_PROMOTION_BLOCKED / REPAIR_ACTIVE` |
| **Executor ativo** | `Codex`, único escritor; início nominal autorizado em `2026-08-11T14:40:10-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.7-r1-concurrent-resume`, criada de `f7aa43a`; sem upstream |
| **Main atual** | `main == origin/main == f7aa43a154e36d29f9882f060cf23294d8194b3e`; promoção F4.7 bloqueada |
| **CI pós-merge** | run `31528955883`: 9 jobs verdes; Tests Windows 3.11 e `CI required` falharam |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **Commits F4.7** | gate `d1e9b1f`; produto certificado `bbc2d93963c9c9fdfd5dfffa2d44c64439862c72` |
| **PR F4.7** | [#46](https://github.com/Wf-ops1/Harnessinfra/pull/46), aberto contra `main`; head inicial `054bf6e` |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F4.6 — detectar stack e resolver comandos efetivos, promovida e arquivada |
| PR de implementação | PR #44; head final `00e83574da789fa58f22f928b5290b9471264a63`; run `31505324814`, 11/11 |
| Promoção | merge `a4fd1dabe09c9f6064f7c34b0ddb6bc62761135d`; run `31510277593`, 11/11 |
| Reconciliação administrativa | PR #45; head final `09ced2f8ca7aec6d76562b49511e97db21bdd29d`; run `31512605530`, 11/11 |
| Baseline final | merge `b578515f9ee24b1d72dffcca8756b80586862fd8`; run `31513097203`, 11/11 |
| Fronteira | branch remota de implementação preservada; checkpoints somente locais; nenhuma tag publicada ou ref excluída |

O histórico `POST_PROMOTION_BLOCKED` da F4.1 permanece encerrado pela corretiva F4.C1. As evidências
negativas R2/R3 da F4.6 continuam no dossiê; perderam precedência operacional somente depois do R3,
da recertificação integral, da CI do head final e da CI pós-merge verdes.

## 5. Tarefa ativa

A F4.7 substituiu o resultado transitório `passed/all_passed` por evidência durável por gate: status
fechado, obrigatoriedade, `argv`, cwd, início/fim/duração, exit code, saída limitada/redigida e SHA do
commit verificado. O lifecycle agora termina a travessia em `VERIFYING`, deriva a suíte da policy
compilada, persiste write-ahead/outcome e payloads content-addressed e relê toda a evidência sob o lock
canônico antes de permitir `COMPLETED`. A CLI não aceita mais subconjunto manual e propaga falha por
exit code diferente de zero.

O aceite focado concluiu `45 passed, 1 skipped`; o guard de lifecycle, `76 passed`; a compatibilidade
Fase 4, `128 passed, 2 skipped`; e a regressão integral final, `751 passed, 5 skipped, 6 subtests
passed`. Mypy Windows/Linux passou em 106 arquivos; Ruff, compileall, diff check, build e smoke da
wheel isolada estão verdes. O produto certificado está em `bbc2d93`; detalhes e evidência negativa
intermediária permanecem no dossiê F4.7.

O PR #46 passou 11/11 no head `0757e26` pelo run `31528005230` e foi incorporado pelo merge
`f7aa43a`. A CI pós-merge `31528955883` reabriu o gate: os unitários passaram (`738 passed, 4
skipped`), mas o E2E concorrente aceitou somente a interleaving “um ok + um verification_required”.
No Windows 3.11 ambos os workers retornaram `ok` idempotente, mantendo efeito único e `VERIFYING`.

Repair/retry, orçamento e reexecução pertencem à F4.8; promoção/rollback Git pertencem à F3.7.
F3.7 permanece depois da F4.7. A F4.7 não pode criar worktree, implementar essas tarefas nem
publicar efeitos remotos.

## 6. Bloqueios atuais

O R1 precisa congelar e provar as duas interleavings seguras sem relaxar efeito único, journal único ou
estado final. O gate documental e `checkpoint/f4.7-r1-ready` precedem qualquer mudança no teste.
Produto, dependências, CI, schemas, defaults e policies permanecem fora do escopo. Novo push/PR,
merge, tag remota, exclusão de refs e início de F4.8/F3.7 continuam bloqueados até recertificação.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
VALIDAR O GATE F4.7-R1, CRIAR O COMMIT DOCUMENTAL E `checkpoint/f4.7-r1-ready`. SOMENTE DEPOIS,
AJUSTAR O TESTE CONCORRENTE NA ALLOWLIST E REPETIR A RECERTIFICAÇÃO INTEGRAL.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.7.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch R1, main `f7aa43a`, PR #46, runs `31528005230`/`31528955883`, runtime 3.12.13 e
   checkpoints `checkpoint/f4.7-ready`, `checkpoint/f4.7-complete` e
   `checkpoint/f4.7-r1-ready`.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T17:09:48-03:00 | Fonte: PR #46 + CI pós-merge 31528955883 + R1*
