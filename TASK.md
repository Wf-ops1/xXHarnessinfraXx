# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.8](docs/tasks/active/F4.8.md): único dossiê ativo e escopo congelado do repair loop.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.7 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.8 — repair loop orientado pelos gates |
| **Gate** | F4.8 `READY / IMPLEMENTATION_NOT_STARTED`; checkpoint ainda pendente |
| **Executor ativo** | `Codex`, único escritor; início nominal autorizado em `2026-08-11T19:59:55-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.8-verification-repair-loop`, criada de `main == origin/main == d4e34c7`; sem upstream |
| **Main atual** | `main == origin/main == d4e34c7404d28a10969ab4b322748d01ae5805bf` |
| **CI pós-merge** | run `31541047111`, evento `push`: 11/11 success no SHA exato de `main` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **PRs F4.7** | [#46](https://github.com/Wf-ops1/Harnessinfra/pull/46) incorporado em `f7aa43a`; corretivo [#47](https://github.com/Wf-ops1/Harnessinfra/pull/47) incorporado em `4aa701a` |
| **PR administrativo** | [#48](https://github.com/Wf-ops1/Harnessinfra/pull/48), incorporado em `d4e34c7`; pós-merge verde |

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

A F4.8 foi autorizada após o fechamento administrativo da F4.7. O baseline focado reproduziu
`6 passed, 1 warning`: a F4.7 recupera a mesma reprovação sem rerun, enquanto o `RetryContext` F2.6
permanece restrito ao retry interno do grafo. O dossiê ativo congela a composição canônica,
tentativas dirigidas seguidas de suíte integral e limites duráveis de nó, execução, tokens, custo e
tempo. Nenhum código de produto foi alterado.

A F4.7 está `PROMOTED / RECONCILED / CLOSED`. A F3.7 permanece depois da conclusão e reconciliação
da F4.8; promoção/cherry-pick/revert Git continuam fora do escopo atual.

## 6. Bloqueios atuais

O gate documental F4.8 está `READY`, mas produto permanece bloqueado até o commit documental e
`checkpoint/f4.8-ready`. O bloqueio técnico comprovado é a ausência da ligação entre resultado
canônico F4.7 e nó corretor; orçamento hoje apenas transportado no payload não conta.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
REVALIDAR O DOSSIÊ READY, CRIAR O COMMIT DOCUMENTAL E checkpoint/f4.8-ready.
NÃO ALTERAR PRODUTO ANTES DESSE CHECKPOINT.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo, `docs/tasks/active/F4.8.md` e `docs/tasks/completed/F4.7.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch `task/f4.8-verification-repair-loop`, main `d4e34c7`, PRs #46/#47/#48, run
   pós-administrativo `31541047111`, baseline focado `6 passed` e runtime 3.12.13.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T19:59:55-03:00 | Fonte: F4.8 + PR #48 + CI 31541047111 + DEC-015*
