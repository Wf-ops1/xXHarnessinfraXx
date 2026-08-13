# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.3](docs/tasks/active/F5.3.md): contrato congelado e evidência corrente.
3. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas.
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
| **Tarefa ativa** | F5.3 — trust boundary integrado |
| **Gate** | `PUBLISHED / PR_PENDING / PROMOTION_PENDING` |
| **Executor ativo** | `Codex`, único escritor; implementação autorizada em `2026-08-12T21:37:31-03:00` e publicação autorizada em `2026-08-12T22:43:08-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.3-trust-boundary`, publicada e acompanhando `origin/task/f5.3-trust-boundary`; produto certificado em `f34409a` |
| **Baseline** | `main == origin/main == 0607a0b385da1a864f629bf4811810a574d03768` antes da branch |
| **Gate F5.3** | [dossiê ativo](docs/tasks/active/F5.3.md); `checkpoint/f5.3-ready` documental e `checkpoint/f5.3-complete` local certificado |
| **Certificação local** | focado `283 passed, 2 skipped`; integral `827 passed, 5 skipped, 6 subtests passed`; wheel/smoke verdes |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.2 — política unificada de autorização de tools |
| Produto | commit `ac665b9`; certificação local `811 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), head final `4dccce3`, CI `31644174160`, 11/11 success |
| Merge de produto | `df5fee5b97e4c0613327043a71bc665eacf46aa1`; CI de `push` `31646282269`, 11/11 success |
| Reconciliação | PR administrativo [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge `0607a0b385da1a864f629bf4811810a574d03768` |
| CI final | run `31650131258`, evento `push`, 11/11 success no SHA exato `0607a0b` |
| Fronteira | `checkpoint/f5.2-ready` e `checkpoint/f5.2-complete` somente locais; branches remotas preservadas; nenhuma tag/ref removida |
| Promoção anterior | F5.1: PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A F5.3 pode alterar somente trust/security, compilador,
policy/tool runtime, adapters, worktree, promoção/hooks, leitura autorizada de credenciais, testes e
documentação listados no dossiê. F5.4–F5.7, dependências, lockfile, CI e composição automática ampla
do lifecycle permanecem fora do escopo.

## 5. Tarefa ativa

A [F5.3](docs/tasks/active/F5.3.md) está `PUBLISHED / PR_PENDING / PROMOTION_PENDING`. Uma fronteira
tipada, estrita, congelada, determinística e default-restricted agora governa imports Python, aliases de subprocesso,
worktree exato, hooks, promoção e nomes de secrets. O snapshot não secreto integra o bundle e resume
falha quando marcador, raiz, capacidades ou digest divergem, sem antecipar as F5.4–F5.7.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. Implementação, regressão integral, qualidade, wheel e smoke
isolado estão concluídos, e o commit certificado `f34409a` foi publicado na branch. O workflow não
executa em `push` para `task/**`; a CI será disparada pelo futuro PR contra `main`. PR, merge, tags
remotas, remoção de branch/ref, force-push e bypass não estão autorizados.
Marcador, modo `trusted` ou configuração do projeto nunca podem substituir policy, allowlist,
worktree exato ou aprovação.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL NOVA PARA ABRIR O PR F5.3 CONTRA MAIN.
NÃO ABRIR PR, MESCLAR, CRIAR TAG REMOTA OU REMOVER REFS SEM ESSA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel e `docs/tasks/active/F5.3.md` integralmente.
2. Confirme branch `task/f5.3-trust-boundary`, checkpoint READY e baseline `0607a0b`.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist do dossiê.
4. Reproduza qualquer evidência negativa nova e não reduza critérios para obter verde.
5. Execute somente a próxima ação exata; efeitos remotos exigem autorização nominal nova.

---

*Atualizado em: 2026-08-12T22:43:08-03:00 | Fonte: publicação F5.3 no SHA f34409a + certificação local + PRs #55/#56 + runs 31644174160/31646282269/31650131258 + merge 0607a0b*
