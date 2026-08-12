# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.8](docs/tasks/completed/F4.8.md): dossiê promovido e em reconciliação administrativa.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.8 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Pausa administrativa pós-F4.8; nenhuma implementação ativa |
| **Tarefa ativa** | nenhuma tarefa ativa; somente reconciliação documental da F4.8 |
| **Gate** | F4.8 `PROMOTED / RECONCILIATION_LOCAL_READY`; publicação administrativa pendente |
| **Executor ativo** | `Codex`, único escritor da reconciliação administrativa |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.8`, local e sem upstream, criada de `main == origin/main == 72f89e3ede8c4d7457857c13115f690d87df4aad` |
| **Checkpoints F4.8** | somente locais: READY `bb6752c1f1524b8c747cddc55e74ed7e6491e845`; COMPLETE `5bf0d75e6878f0d1362e0b2053a228a95ec80cef` |
| **PR F4.8** | [#49](https://github.com/Wf-ops1/Harnessinfra/pull/49), head final `f9c8c2d5d2e1f53ef857119886c16b8b2b2c1d8d`; run `31550975708`, 11/11 success |
| **Main atual** | `main == origin/main == 72f89e3ede8c4d7457857c13115f690d87df4aad` |
| **CI pós-merge** | run `31551685950`, evento `push`: 11/11 success no SHA exato de `main` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **PR administrativo anterior** | [#48](https://github.com/Wf-ops1/Harnessinfra/pull/48), incorporado em `d4e34c7`; pós-merge `31541047111` verde |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F4.8 — repair loop orientado pelos gates |
| Produto | `8e5e11d81c685c53ba349bab4d95cdd61ee19ba6`; certificação `5bf0d75e6878f0d1362e0b2053a228a95ec80cef` |
| Pull request | PR #49; head final `f9c8c2d5d2e1f53ef857119886c16b8b2b2c1d8d`; run `31550975708`, 11/11 success |
| Promoção | merge `72f89e3ede8c4d7457857c13115f690d87df4aad`; run pós-merge `31551685950`, 11/11 success |
| Reconciliação | `LOCAL_READY / PUBLICATION_PENDING` em `docs/promote-f4.8`; gate documental `26 passed, 6 subtests passed`, Ruff e diff check verdes |
| Fronteira | branch de produto remota preservada; checkpoints somente locais; nenhuma tag publicada ou ref excluída |

A CI do PR e a CI de `push` no merge exato estão verdes. Nenhuma evidência negativa posterior foi
observada. O atraso restante é exclusivamente documental e está isolado pela DEC-014.

## 5. Tarefa ativa

Não existe tarefa de implementação ativa. A F4.8 consumiu a última reprovação canônica F4.7,
construiu `RetryContext` redigido para o `on_failure` compilado e persistiu contexto, deadline,
policy, orçamento e cursor antes do efeito corretivo. Após o reparo, o lifecycle executa os gates
antes reprovados e exige a suíte integral no mesmo commit limpo antes de `COMPLETED`. Os limites por
nó, execução, tokens, custo e tempo terminam duravelmente em `FAILED_RETRY_EXHAUSTED`.

O aceite local final concluiu `758 passed, 5 skipped`; mypy, Ruff, compileall, diff check, build PEP
517 e smoke externo da wheel `0.1.0` ficaram verdes. O E2E cobre commit quebrado, novo commit de
reparo, targeted → full, crash-resume no CAS do cursor sem duplicar efeito e exaustão dos limites.

O PR #49 encerrou no head `f9c8c2d`, recebeu 11/11 checks no run `31550975708`, foi incorporado pelo
merge `72f89e3` e recebeu 11/11 na CI pós-merge `31551685950`. A F4.8 está `PROMOTED`; o dossiê foi
movido para `completed/` e a reconciliação local passou no gate documental, Ruff e diff check.

A F3.7 não foi iniciada e permanece fora do escopo até o PR administrativo da F4.8 ser incorporado e
sua CI pós-merge ficar verde.

## 6. Bloqueios atuais

Não há bloqueio técnico ou documental conhecido na F4.8. A reconciliação está
`LOCAL_READY / PUBLICATION_PENDING`; falta autorização explícita para publicar `docs/promote-f4.8` e
abrir seu PR administrativo. Push, abertura de PR, merge, tag remota e início da F3.7 não estão
autorizados por esta reconciliação local.

Evidência negativa nova sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO EXPLÍCITA PARA PUSH E ABERTURA DO PR ADMINISTRATIVO DA F4.8.
NÃO INICIAR F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/completed/F4.8.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch `docs/promote-f4.8`, base/main `72f89e3`, PR #49 no head `f9c8c2d`, run do PR
   `31550975708`, run pós-merge `31551685950`, regressão `758 passed` e runtime 3.12.13.
4. Confirme que não há dossiê de implementação ativo e execute somente a próxima ação exata.

---

*Atualizado em: 2026-08-11T22:05:52-03:00 | Fonte: F4.8 + PR #49 + merge 72f89e3 + CI 31551685950 + gate documental local + DEC-014/DEC-015*
