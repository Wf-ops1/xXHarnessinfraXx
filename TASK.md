# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.4](docs/tasks/completed/F5.4.md): promoção comprovada e reconciliação administrativa corrente.
3. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
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
| **Tarefa ativa** | nenhuma tarefa ativa; F5.5 — integrar secrets e redaction — está somente planejada e não autorizada |
| **Gate** | `PROMOTED / ADMIN_RECONCILIATION_LOCAL` |
| **Executor ativo** | `Codex`, único escritor da reconciliação iniciada em `2026-08-13T17:50:35-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch administrativa** | `docs/promote-f5.4`, local e sem upstream |
| **Baseline** | `main == origin/main == d6246295045a156646af14de0011400feb6cb4f3` antes da branch |
| **Produto F5.4** | `722916b0d5c9eddb0a06151894701e3f16e113aa` |
| **Head final do PR** | `21aa4a6134db38615eed8c11cc15285924a62365` |
| **CI do PR** | run [31739876952](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31739876952), `pull_request`, 11/11 success no head final |
| **Promoção F5.4** | PR [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), merge `d6246295045a156646af14de0011400feb6cb4f3` |
| **CI pós-merge** | run [31742231398](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31742231398), `push`, 11/11 success em 5m15s no merge exato |
| **Reconciliação** | `LOCAL_READY / PUBLICATION_PENDING`; ainda não incorporada em `main` |
| **Checkpoints** | `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.4 — integrar orçamento durável por execução e nó |
| Produto | commit `722916b`; certificação local `856 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), head final `21aa4a6`, CI `31739876952`, 11/11 success |
| Merge de produto | `d6246295045a156646af14de0011400feb6cb4f3`; CI de `push` `31742231398`, 11/11 success |
| Fronteira | `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais; branch remota preservada; nenhuma tag/ref removida |
| Promoção anterior | F5.3 — trust boundary integrado: PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head `4934aee`, CI `31659293351`; merge `211edcf921912a32429934bf600473d8cc98941c`, pós-merge `31660030240`; reconciliação [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), merge/CI final `4c0527baacc74821112adf7fe61b82af72589f69` / `31728438719`; fronteira `default-restricted` e checkpoints `checkpoint/f5.3-ready`/`checkpoint/f5.3-complete` somente locais |
| Promoção F5.2 preservada | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A reconciliação pode alterar apenas `README.md`,
`TASK.md`, `docs/tasks/README.md`, o dossiê F5.4 movido para `completed/` e testes documentais/de
ledger afetados. Produto, dependências, schemas, defaults, lockfile e CI estão proibidos.

## 5. Tarefa ativa

Não há implementação ativa. A F5.4 — integrar orçamento durável por execução e nó — está promovida
no Git/GitHub: o journal governa o saldo canônico por execução/nó, reserva antes do efeito e conduz
excesso a `FAILED_BUDGET_EXCEEDED`, com projeção única em `status`/`inspect`. A reconciliação
documental ainda precisa ser validada, publicada, revisada e incorporada. A F5.5 — integrar secrets
e redaction — permanece apenas planejada; nenhum gate F5.5 foi congelado ou autorizado.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. Publicar `docs/promote-f5.4`, abrir ou mesclar seu PR
administrativo, publicar tags, remover branch/ref, fazer force-push/bypass ou iniciar a F5.5 não
estão autorizados.

## 7. Próxima ação exata

```text
VALIDAR E COMMITAR LOCALMENTE A RECONCILIAÇÃO docs/promote-f5.4.
AGUARDAR AUTORIZAÇÃO PARA PUBLICAR A BRANCH E ABRIR O PR ADMINISTRATIVO ÚNICO DA F5.4.
NÃO MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.5 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F5.4.md` e a DEC-014.
2. Confirme branch `docs/promote-f5.4`, baseline `d624629` e diff estritamente documental.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist administrativa.
4. Execute somente a próxima ação exata; publicação, PR administrativo, merge e F5.5 exigem nova autorização.

---

*Atualizado em: 2026-08-13T17:50:35-03:00 | Fonte: F5.4 + PR #59 + runs 31739876952/31742231398 + merge d624629*
