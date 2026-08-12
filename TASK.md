# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.2](docs/tasks/completed/F5.2.md): promoção comprovada e reconciliação administrativa corrente.
3. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
4. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
5. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
6. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | nenhuma tarefa ativa; F5.3 está somente planejada e não autorizada |
| **Gate** | `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor da reconciliação iniciada em `2026-08-12T19:22:50-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch administrativa** | `docs/promote-f5.2` rastreando `origin/docs/promote-f5.2` |
| **Baseline** | `main == origin/main == df5fee5b97e4c0613327043a71bc665eacf46aa1` antes da branch |
| **Produto F5.2** | `ac665b945a2cfbadaa7672855219e624d7eca45e` |
| **Head final do PR** | `4dccce3877d4b8d715efb7ab8212ff1ee0bff1a2` |
| **CI do PR** | run [31644174160](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31644174160), `pull_request`, 11/11 success no head final |
| **Promoção F5.2** | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1` |
| **CI pós-merge** | run [31646282269](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31646282269), `push`, 11/11 success no merge exato |
| **Reconciliação** | PR [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), não draft; head inicial `73fb40d`; `ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Checkpoints** | `checkpoint/f5.2-ready` e `checkpoint/f5.2-complete` somente locais |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.2 — política unificada de autorização de tools |
| Produto | commit `ac665b9`; certificação local `811 passed, 5 skipped, 6 subtests passed` |
| Pull request | #55, head final `4dccce3`, CI `31644174160` com 11/11 success |
| Merge | `df5fee5`, preservando a branch de produto |
| Pós-merge | CI `31646282269`, evento `push`, 11/11 success no SHA exato |
| Fronteira | checkpoints somente locais; nenhuma tag/ref remota removida |
| Promoção anterior | F5.1: PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A reconciliação pode alterar apenas `README.md`,
`TASK.md`, `docs/tasks/README.md`, o dossiê F5.2 movido para `completed/` e testes documentais/de
ledger afetados. Produto, dependências, schemas, defaults, lockfile e CI estão proibidos.

## 5. Tarefa ativa

Não há nenhuma tarefa ativa de implementação. A F5.2 está promovida no Git/GitHub, mas sua
reconciliação documental ainda precisa ser validada, publicada, revisada e incorporada. A F5.3
permanece apenas planejada no plano principal; nenhum gate F5.3 foi congelado ou autorizado.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A branch administrativa foi publicada e o PR #56 está aberto; a
publicação deste registro cria o head documental final, que exige CI integral. Mesclar o PR, publicar
tags, remover branch/ref, fazer force-push/bypass ou iniciar a F5.3 não estão autorizados.

## 7. Próxima ação exata

```text
AUDITAR TODOS OS CHECKS DO HEAD FINAL DO PR ADMINISTRATIVO #56 APÓS PUBLICAR ESTE REGISTRO.
NÃO MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.3 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F5.2.md` e a DEC-014.
2. Confirme branch `docs/promote-f5.2`, baseline `df5fee5` e diff estritamente documental.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist administrativa.
4. Execute somente a próxima ação exata; publicação, PR administrativo, merge e F5.3 exigem nova autorização.

---

*Atualizado em: 2026-08-12T19:54:59-03:00 | Fonte: F5.2 + PRs #55/#56 + runs 31644174160/31646282269 + merge df5fee5*
