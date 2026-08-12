# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.1](docs/tasks/completed/F5.1.md): promoção comprovada e reconciliação administrativa corrente.
3. [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md), pós-merge `31568908128`, e
   [F4.8](docs/tasks/completed/F4.8.md): entregas promovidas anteriores.
4. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
5. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | nenhuma tarefa ativa; F5.2 está somente planejada e não autorizada |
| **Gate** | `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor; reconciliação autorizada nominalmente em `2026-08-12T16:17:23-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch administrativa** | `docs/promote-f5.1`, publicada e rastreando `origin/docs/promote-f5.1` |
| **Baseline** | `main == origin/main == c46910e50ede1196c9beb1242cb7bd708905d666` antes da branch |
| **Produto F5.1** | `f246feb2a70bb83f08ff31341525fd29bd6d10f8` |
| **Head final do PR** | `f42af272c54b2610554eb34acd75dc895a011974` |
| **CI do PR** | run [31629604755](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31629604755), `pull_request`, 11/11 success no head final |
| **Promoção F5.1** | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), merge `c46910e50ede1196c9beb1242cb7bd708905d666` |
| **CI pós-merge** | run [31630446370](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31630446370), `push`, 11/11 success no merge exato |
| **Reconciliação** | PR administrativo [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), aberto e não draft; head inicial `f7e1173` |
| **Checkpoints** | `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.1 — resolver configuração no início da execução |
| Produto | commit `f246feb`; certificação local integral `792 passed, 5 skipped, 6 subtests passed` |
| Pull request | #53, head final `f42af27`, CI `31629604755` com 11/11 success |
| Merge | `c46910e`, preservando a branch de produto |
| Pós-merge | CI `31630446370`, evento `push`, 11/11 success no SHA exato |
| Fronteira | checkpoints somente locais; nenhuma tag/ref remota removida |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A reconciliação pode alterar apenas `README.md`,
`TASK.md`, `docs/tasks/README.md`, o dossiê F5.1 movido para `completed/` e testes documentais/de
ledger afetados. Produto, dependências, schemas, defaults, lockfile e CI estão proibidos.

## 5. Tarefa ativa

Não há nenhuma tarefa ativa de implementação. A F5.1 está promovida no Git/GitHub, mas sua
reconciliação documental ainda precisa ser publicada, revisada e incorporada. A F5.2 permanece apenas
planejada no plano principal; nenhum gate F5.2 foi congelado ou autorizado.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A branch foi publicada e o PR administrativo #54 foi aberto. A
autorização corrente não inclui o merge desse PR. Tag remota, exclusão de branch/ref, force-push,
bypass e início da F5.2 continuam proibidos.

## 7. Próxima ação exata

```text
OBSERVAR TODOS OS CHECKS DO HEAD FINAL DO PR ADMINISTRATIVO #54.
NÃO MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.2 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F5.1.md` e a DEC-014.
2. Confirme branch `docs/promote-f5.1`, PR #54, baseline `c46910e` e diff estritamente documental.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist administrativa.
4. Execute somente a próxima ação exata; o merge administrativo e a F5.2 exigem nova autorização.

---

*Atualizado em: 2026-08-12T16:25:41-03:00 | Fonte: F5.1 + PRs #53/#54 + runs 31629604755/31630446370 + merge c46910e*
