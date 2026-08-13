# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.3](docs/tasks/completed/F5.3.md): promoção comprovada e reconciliação administrativa corrente.
3. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
4. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
5. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
6. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
7. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | nenhuma tarefa ativa; F5.4 — integrar orçamento — está somente planejada e não autorizada |
| **Gate** | `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor da reconciliação iniciada em `2026-08-12T23:19:24-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch administrativa** | `docs/promote-f5.3`, publicada e acompanhando `origin/docs/promote-f5.3` |
| **Baseline** | `main == origin/main == 211edcf921912a32429934bf600473d8cc98941c` antes da branch |
| **Produto F5.3** | `f34409aeb197612d866be0576d5bc21d00e0a8f1` |
| **Head final do PR** | `4934aee925830e4aac2672b0bbf6ffadbf1c9ca9` |
| **CI do PR** | run [31659293351](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31659293351), `pull_request`, 11/11 success no head final |
| **Promoção F5.3** | PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), merge `211edcf921912a32429934bf600473d8cc98941c` |
| **CI pós-merge** | run [31660030240](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31660030240), `push`, 11/11 success no merge exato |
| **Reconciliação** | commits iniciais `fed4c7050f8891e8b24e874bb9aa2130b9269983` e `7b7af9ea2512e1ea9a606053e39ae43678c83b39`; PR [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58) aberto, não draft; `ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Checkpoints** | `checkpoint/f5.3-ready` e `checkpoint/f5.3-complete` somente locais |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.3 — trust boundary integrado |
| Produto | commit `f34409a`; certificação local `827 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head final `4934aee`, CI `31659293351`, 11/11 success |
| Merge de produto | `211edcf921912a32429934bf600473d8cc98941c`; CI de `push` `31660030240`, 11/11 success |
| Fronteira | `checkpoint/f5.3-ready` e `checkpoint/f5.3-complete` somente locais; branch remota preservada; nenhuma tag/ref removida |
| Promoção anterior | F5.2: PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), head `4dccce3`, CI `31644174160`; merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A reconciliação pode alterar apenas `README.md`,
`TASK.md`, `docs/tasks/README.md`, o dossiê F5.3 movido para `completed/` e testes documentais/de
ledger afetados. Produto, dependências, schemas, defaults, lockfile e CI estão proibidos.

## 5. Tarefa ativa

Não há implementação ativa. A F5.3 — trust boundary integrado — está promovida no Git/GitHub: sua
fronteira tipada e `default-restricted` governa imports, comandos, worktree, hooks, promoção e nomes
de secrets. A reconciliação documental foi publicada no PR #58 e ainda precisa ter seu head final
certificado e ser incorporada. A F5.4 — integrar orçamento — permanece apenas planejada no plano principal; nenhum
gate F5.4 foi congelado ou autorizado.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A publicação de `docs/promote-f5.3` e a abertura do PR #58 foram
autorizadas e concluídas. Mesclar o PR administrativo, publicar tags, remover branch/ref, fazer
force-push/bypass ou iniciar a F5.4 não estão autorizados.

## 7. Próxima ação exata

```text
PUBLICAR ESTE REGISTRO PARA FORMAR O HEAD FINAL E AUDITAR TODOS OS CHECKS DO PR #58.
NÃO MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.4 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F5.3.md` e a DEC-014.
2. Confirme branch `docs/promote-f5.3`, PR #58, baseline `211edcf` e diff estritamente documental.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist administrativa.
4. Execute somente a próxima ação exata; merge, tags/refs e F5.4 exigem nova autorização.

---

*Atualizado em: 2026-08-13T14:39:07-03:00 | Fonte: F5.3 + PRs #57/#58 + runs 31659293351/31660030240 + merge 211edcf*
