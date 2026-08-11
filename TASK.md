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
| **Gate** | F4.7 `READY / COMPLETED_LOCAL / PROMOTION_PENDING`; aceite local integral verde |
| **Executor ativo** | `Codex`, único escritor; início nominal autorizado em `2026-08-11T14:40:10-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.7-persist-verification-results`, criada de `b578515`; sem upstream |
| **Baseline promovido** | `main == origin/main == b578515f9ee24b1d72dffcca8756b80586862fd8` antes da branch F4.7 |
| **CI do baseline** | run `31513097203`, evento `push`, 11/11 verde em `3m05s`, inclusive `CI required` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **Commits F4.7** | gate `d1e9b1f`; produto certificado `bbc2d93963c9c9fdfd5dfffa2d44c64439862c72` |

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

Repair/retry, orçamento e reexecução pertencem à F4.8; promoção/rollback Git pertencem à F3.7.
F3.7 permanece depois da F4.7. A F4.7 não pode criar worktree, implementar essas tarefas nem
publicar efeitos remotos.

## 6. Bloqueios atuais

Não há blocker técnico local. A publicação da branch e a abertura do PR aguardam autorização nominal
nova. Push, PR, merge, tag remota e exclusão de refs não foram executados; CI da branch ainda não
existe. O checkpoint local `checkpoint/f4.7-ready` aponta para `d1e9b1f`; o checkpoint local
`checkpoint/f4.7-complete` aponta para a certificação `a706b7fb8ce6ca6ea7a3a2a65f7ad4ab7630bf6a`.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
SOLICITAR AUTORIZAÇÃO NOMINAL PARA PUBLICAR `task/f4.7-persist-verification-results` E ABRIR O PR F4.7.
NÃO FAZER MERGE, PUBLICAR TAG REMOTA, EXCLUIR REF OU INICIAR F4.8/F3.7 SEM AUTORIZAÇÃO ESPECÍFICA.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.7.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme `task/f4.7-persist-verification-results`, produto `bbc2d93`, baseline `b578515`, run
   pós-merge `31513097203`, runtime 3.12.13 e checkpoints `checkpoint/f4.7-ready` e
   `checkpoint/f4.7-complete`.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T16:09:17-03:00 | Fonte: aceite integral F4.7 + DEC-014/DEC-015 + Git local*
