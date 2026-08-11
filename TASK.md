# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.7](docs/tasks/completed/F4.7.md): dossiê promovido em reconciliação administrativa.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.7 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | nenhuma tarefa ativa de implementação; reconciliação administrativa da F4.7 |
| **Gate** | F4.7 `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor; início nominal autorizado em `2026-08-11T14:40:10-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.7`, criada de `main == origin/main == 4aa701a`; upstream publicado |
| **Main atual** | `main == origin/main == 4aa701a9394e5bdcb9c14dc5a9a715638c183258` |
| **CI pós-merge** | run `31534918672`, evento `push`: 11/11 success no SHA exato de `main` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **PRs F4.7** | [#46](https://github.com/Wf-ops1/Harnessinfra/pull/46) incorporado em `f7aa43a`; corretivo [#47](https://github.com/Wf-ops1/Harnessinfra/pull/47) incorporado em `4aa701a` |
| **PR administrativo** | [#48](https://github.com/Wf-ops1/Harnessinfra/pull/48), aberto no head inicial `e198e5b7`; checks pendentes |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F4.7 — persistência e guard canônico dos resultados de verificação |
| Implementação | PR #46; head `0757e26097a96b09de5fb9bc569599e46f6e6170`; run `31528005230`, 11/11 |
| Evidência negativa | merge `f7aa43a154e36d29f9882f060cf23294d8194b3e`; run `31528955883` falhou no E2E concorrente Windows 3.11 |
| Corretiva R1 | PR #47; head `b79e14d2ba2c76514b7e6a6b22017b02348e6453`; run `31533353223`, 11/11 |
| Promoção restaurada | merge `4aa701a9394e5bdcb9c14dc5a9a715638c183258`; run `31534918672`, 11/11 |
| Fronteira | branches remotas preservadas; checkpoints somente locais; nenhuma tag publicada ou ref excluída |

O histórico `POST_PROMOTION_BLOCKED` da F4.1 permanece encerrado pela corretiva F4.C1. A falha
pós-merge da F4.7 permanece no dossiê como evidência temporal; perdeu precedência operacional somente
após R1, recertificação integral, CI do PR #47, merge corretivo e CI pós-merge verdes.

## 5. Tarefa ativa

A F4.7 substituiu o resultado transitório `passed/all_passed` por evidência durável por gate: status
fechado, obrigatoriedade, `argv`, cwd, início/fim/duração, exit code, saída limitada/redigida e SHA do
commit verificado. O lifecycle agora termina a travessia em `VERIFYING`, deriva a suíte da policy
compilada, persiste write-ahead/outcome e payloads content-addressed e relê toda a evidência sob o lock
canônico antes de permitir `COMPLETED`. A CLI não aceita mais subconjunto manual e propaga falha por
exit code diferente de zero.

O aceite focado concluiu `45 passed, 1 skipped`; o guard de lifecycle, `76 passed`; a compatibilidade
Fase 4, `128 passed, 2 skipped`; e a regressão integral final, `751 passed, 5 skipped, 6 subtests
passed`. Mypy Windows/Linux, Ruff, compileall, diff check, build e smoke isolado estão verdes.

O PR #46 passou 11/11, mas sua CI pós-merge `31528955883` materializou a segunda interleaving segura.
O R1 em `2841346a` alterou somente o teste, passou a corrida `20/20` e toda a recertificação. O PR #47
e seu merge receberam 11/11 nos runs `31533353223` e `31534918672`, inclusive Windows 3.11 e
`CI required`. O dossiê foi marcado `PROMOTED` e movido para `completed/` nesta reconciliação.

Repair/retry, orçamento e reexecução pertencem à F4.8; promoção/rollback Git pertencem à F3.7. A
F3.7 permanece depois da F4.7 e de seu fechamento administrativo. Essas tarefas não podem começar
antes do PR administrativo e de sua CI pós-merge verde.

## 6. Bloqueios atuais

Não há bloqueio técnico da F4.7. O PR administrativo #48 está aberto; seu head documental final ainda
precisa passar em todos os checks. Merge administrativo, tag remota, exclusão de refs e início de
F4.8/F3.7 exigem autorização nominal nova.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
PUBLICAR O REGISTRO DO PR #48 E OBSERVAR TODOS OS CHECKS DO HEAD FINAL.
NÃO MESCLAR SEM AUTORIZAÇÃO NOMINAL NOVA.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/completed/F4.7.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch `docs/promote-f4.7`, main `4aa701a`, PRs #46/#47/#48, runs
   `31528005230`/`31528955883`/`31533353223`/`31534918672` e runtime 3.12.13.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T18:21:21-03:00 | Fonte: PRs #46/#47/#48 + CI pós-merge 31534918672 + DEC-014*
