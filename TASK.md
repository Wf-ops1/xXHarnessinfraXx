# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.4](docs/tasks/active/F5.4.md): gate corrente de orçamento durável, congelado antes da implementação.
3. [F5.3](docs/tasks/completed/F5.3.md): promoção e reconciliação administrativa comprovadas.
4. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
5. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
6. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
7. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
8. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.4 — integrar orçamento durável por execução e nó |
| **Gate** | `READY / ACTIVE / LOCAL_ONLY` |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-13T15:18:42-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch da tarefa** | `task/f5.4-durable-budget`, local e sem upstream |
| **Baseline** | `main == origin/main == 4c0527baacc74821112adf7fe61b82af72589f69` antes da branch |
| **Produto F5.3** | `f34409aeb197612d866be0576d5bc21d00e0a8f1` |
| **Head final do PR** | `4934aee925830e4aac2672b0bbf6ffadbf1c9ca9` |
| **CI do PR** | run [31659293351](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31659293351), `pull_request`, 11/11 success no head final |
| **Promoção F5.3** | PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), merge `211edcf921912a32429934bf600473d8cc98941c` |
| **CI pós-merge** | run [31660030240](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31660030240), `push`, 11/11 success no merge exato |
| **Reconciliação F5.3** | PR [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), head `9d53e4156382e24c25b206aa50fdaed3e03ee2dd`, merge `4c0527baacc74821112adf7fe61b82af72589f69`; CI `31728438719`, 11/11 success |
| **Checkpoint corrente** | `checkpoint/f5.4-ready` somente local → commit documental deste gate |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.3 — trust boundary integrado |
| Produto | commit `f34409a`; certificação local `827 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head final `4934aee`, CI `31659293351`, 11/11 success |
| Merge de produto | `211edcf921912a32429934bf600473d8cc98941c`; CI de `push` `31660030240`, 11/11 success |
| Reconciliação administrativa | PR [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), head `9d53e41`, CI de PR `31727166976`; merge `4c0527b`, CI de `push` `31728438719`, 11/11 success |
| Fronteira | trust boundary `default-restricted`; `checkpoint/f5.3-ready` e `checkpoint/f5.3-complete` somente locais; branch remota preservada; nenhuma tag/ref removida |
| Promoção anterior | F5.2: PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), head `4dccce3`, CI `31644174160`; merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A autorização corrente permite somente criar a branch,
o dossiê F5.4, atualizar documentação/ledger e materializar o checkpoint READY. Produto,
dependências, schemas, defaults, lockfile e CI ainda não podem ser alterados.

## 5. Tarefa ativa

A F5.4 está `READY / ACTIVE / LOCAL_ONLY`, ainda sem implementação. O gate congela um ledger canônico
por execução/nó para prompt/completion tokens, tool calls, duração, tentativas e custo conhecido;
reserva antes do efeito, consumo real depois, replay/resume sem reset ou dupla cobrança e estado
`FAILED_BUDGET_EXCEEDED`. O contador atual do `ModelRouter` permanece apenas process-local até a
implementação ser autorizada.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. Implementar produto, ampliar o escopo congelado, publicar a branch,
abrir/mesclar PR, publicar tags, remover refs, fazer force-push/bypass ou iniciar a F5.5 não estão
autorizados.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO PARA IMPLEMENTAR A F5.4 NO ESCOPO CONGELADO.
NÃO PUBLICAR, ABRIR PR, MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.5.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.4.md` e a Fase 5 do plano.
2. Confirme branch `task/f5.4-durable-budget`, baseline `4c0527b` e checkpoint `checkpoint/f5.4-ready`.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist administrativa.
4. Execute somente a próxima ação exata; implementação, publicação e F5.5 exigem autorização própria.

---

*Atualizado em: 2026-08-13T15:18:42-03:00 | Fonte: F5.4 + F5.3 + PRs #57/#58 + runs 31660030240/31728438719 + merge 4c0527b*
