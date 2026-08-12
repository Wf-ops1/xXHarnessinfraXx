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
| **Gate** | F4.8 `COMPLETED_LOCAL / PROMOTION_PENDING`; produto e certificação local verdes |
| **Executor ativo** | `Codex`, único escritor; início nominal autorizado em `2026-08-11T19:59:55-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.8-verification-repair-loop`, head local de produto `8e5e11d81c685c53ba349bab4d95cdd61ee19ba6`; criada de `main == origin/main == d4e34c7`; sem upstream |
| **Checkpoint READY** | `checkpoint/f4.8-ready` → `bb6752c1f1524b8c747cddc55e74ed7e6491e845` |
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

A F4.8 foi autorizada após o fechamento administrativo da F4.7 e implementada no commit local
`8e5e11d`. O lifecycle agora transforma somente a última reprovação canônica F4.7 em `RetryContext`,
agenda o `on_failure` compilado pelo `GraphExecutor` e persiste contexto, deadline, policy, orçamento e
cursor antes do efeito corretivo. Depois do reparo, executa apenas os gates antes reprovados e, se
passarem, exige a suíte integral no mesmo commit limpo antes de `COMPLETED`. Limites por nó, execução,
tokens, custo contábil da policy e tempo terminam duravelmente em `FAILED_RETRY_EXHAUSTED`.

O E2E real cobre commit quebrado, reparo com novo commit, targeted → full, recuperação de crash no CAS
do cursor sem efeito duplicado e exaustão dos quatro orçamentos. A regressão final concluiu
`758 passed, 5 skipped`; mypy em 106 módulos, Ruff, compileall, diff check, build PEP 517 e smoke externo
da wheel `0.1.0` estão verdes.

A F4.7 está `PROMOTED / RECONCILED / CLOSED`. A F3.7 permanece depois da conclusão e reconciliação
da F4.8; promoção/cherry-pick/revert Git continuam fora do escopo atual.

## 6. Bloqueios atuais

Não resta bloqueio técnico local da F4.8. A promoção permanece bloqueada apenas por processo: branch,
commit de certificação e tags ainda são locais; nenhum push, PR, CI remota ou merge F4.8 ocorreu. A
F3.7 continua fora do escopo até promoção e reconciliação da F4.8.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL PARA PUBLICAR A BRANCH E ABRIR O PR F4.8.
NÃO FAZER PUSH, PR, MERGE, TAG REMOTA, RECONCILIAÇÃO OU INICIAR F3.7 ANTES DISSO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo, `docs/tasks/active/F4.8.md` e `docs/tasks/completed/F4.7.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch `task/f4.8-verification-repair-loop`, produto `8e5e11d`, checkpoint READY
   `bb6752c`, main `d4e34c7`, run pós-administrativo `31541047111`, regressão `758 passed` e runtime
   3.12.13.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T21:03:29-03:00 | Fonte: F4.8 + produto 8e5e11d + PR #48 + CI 31541047111 + DEC-015*
