# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.6](docs/tasks/active/F5.6.md): gate `READY` para aprovação vinculada ao conteúdo.
3. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa incorporada.
4. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
5. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
6. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
7. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
8. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
9. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
10. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.6 — aprovação vinculada ao conteúdo |
| **Gate** | `READY` — problema, escopo, aceite e rollback congelados |
| **Estado corrente** | `ACTIVE / READY` |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-14T10:30:31-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.6-content-bound-approval`, somente local e sem upstream |
| **Checkpoint F5.6** | `checkpoint/f5.6-ready`, commit documental do gate, somente local |
| **Problema F5.6** | JSON legado com 3 campos e subject imune a mudança de candidate reproduzidos por booleanos |
| **Implementação F5.6** | request canônico pós-candidate/gates, diff digest, decisão/expiração/invalidação journaled e guard pré-Git |
| **Matriz focada F5.6** | `47 passed em 187.74s`; node insuficiente, mismatch, expiry, tamper, CAS/recovery e Git real |
| **Regressão F5.6** | `885 passed, 5 skipped, 6 subtests passed em 557.95s` |
| **Quality/distribuição F5.6** | mypy 104 arquivos, Ruff, compileall, diff-check, wheel 0.1.0 e smoke oficial uv 0.12.3 verdes |
| **Branch de produto preservada** | `task/f5.5-secrets-redaction`, remota e não removida |
| **Main sincronizada** | `main == origin/main == daec37d119fced3a5e041c412ab01e7524c15800` antes da branch F5.6; origin confirmado por `ls-remote` |
| **Reconciliação F5.4** | PR [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), head `7613460`, merge `2f4e391bfe3588f713a436b051d4f60e970e4df1` |
| **CI final anterior** | run [31759971204](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31759971204), `push`, 11/11 success em 4m42s no baseline exato |
| **Problema F5.5** | multiline/contexto dinâmico, fallback de credencial OpenAI e `repr` Serena reproduzidos como vazamentos booleanos, sem expor valores |
| **Baseline focado** | R0 inválido por sandbox; R1 válido `230 passed, 3 skipped em 59.15s` |
| **Implementação local** | contexto imutável, provider/Serena/terminal/tool outcome redigidos; fallback secreto removido; matriz focada `192 passed, 3 skipped` |
| **Regressão integral** | `873 passed, 5 skipped, 6 subtests passed em 187.14s` |
| **Quality/build** | ruff, mypy, compileall, diff-check, wheel e smoke oficial offline verdes |
| **Produto** | commit local `f4460ad`; wheel e smoke reconstruídos após esse commit |
| **Checkpoint** | `checkpoint/f5.5-ready` no commit `16bcbb1`; `checkpoint/f5.5-complete` no commit documental de certificação, ambos somente locais |
| **PR F5.5** | [#61](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61), head final `68482da`, CI [31765166979](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31765166979) 11/11 success |
| **Merge F5.5** | `2227b73131d405cde046c58ec83094889a3feb51`; CI pós-merge [31769631054](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31769631054) 11/11 success em 5m20s |
| **PR administrativo F5.5** | [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), head final `45f4fb7`, CI `31770761873` 11/11; merge `daec37d`, CI final `31771169636` 11/11 |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.5 — integrar secrets e redaction no caminho crítico |
| Produto | commit `f4460ad`; focado `192 passed, 3 skipped`; full `873 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#61](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61), head final `68482da`, CI `31765166979`, 11/11 success |
| Merge de produto | `2227b73131d405cde046c58ec83094889a3feb51`; CI de `push` `31769631054`, 11/11 success em 5m20s |
| Reconciliação administrativa | PR [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), head final `45f4fb7`, CI `31770761873` 11/11; merge `daec37d`, CI final `31771169636` 11/11 |
| Fronteira | `checkpoint/f5.5-ready` e `checkpoint/f5.5-complete` somente locais; branch remota de produto preservada; nenhuma tag/ref removida |
| Promoção anterior | F5.4 — PR [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), produto `722916b`, head `21aa4a6`, CI `31739876952`; merge `d624629`, pós-merge `31742231398`; reconciliação [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), merge/CI final `2f4e391` / `31759971204`; certificação local `856 passed, 5 skipped, 6 subtests passed`; checkpoints `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais |
| Promoção anterior | F5.3 — trust boundary integrado: PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head `4934aee`, CI `31659293351`; merge `211edcf921912a32429934bf600473d8cc98941c`, pós-merge `31660030240`; reconciliação [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), merge/CI final `4c0527baacc74821112adf7fe61b82af72589f69` / `31728438719`; fronteira `default-restricted` e checkpoints `checkpoint/f5.3-ready`/`checkpoint/f5.3-complete` somente locais |
| Promoção F5.2 preservada | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. O checkpoint `checkpoint/f5.6-ready` foi materializado em
`161e1c26eb0aad6b81e25ebdcda4f12519486ba4` antes do produto. A implementação permanece restrita à
allowlist congelada; nenhuma publicação foi autorizada.

## 5. Tarefa ativa

A F5.6 possui problema reproduzido, checkpoint READY anterior ao produto e implementação validada.
Contrato/E2E `47 passed`; regressão `885 passed, 5 skipped, 6 subtests passed`; documentação/ledger,
mypy, Ruff, compileall, diff-check, wheel e smoke isolado verdes. Commit local de produto, repetição
build/smoke pós-commit e certificação documental final ainda pendem.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido para implementação. O smoke final depende de `uv`, ausente no
`PATH`, e não autoriza instalação silenciosa. Push, PR, merge, tags remotas, remoção de refs e
force-push/bypass não estão autorizados.

## 7. Próxima ação exata

```text
VALIDAR AS SENTINELAS DOCUMENTAIS F5.6 E CRIAR O COMMIT LOCAL DE PRODUTO.
RECONSTRUIR/TESTAR A WHEEL NO COMMIT EXATO E SÓ ENTÃO CERTIFICAR LOCALMENTE.
NÃO PUBLICAR BRANCH, PR OU TAGS REMOTAS.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.6.md` e a Fase 5 do plano.
2. Confirme branch `task/f5.6-content-bound-approval`, baseline `daec37d` e checkpoint local `checkpoint/f5.6-ready`.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve os critérios congelados.
4. Não publique branch/PR/tags nem altere o escopo sem autorização e recongelamento aplicáveis.

---

*Atualizado em: 2026-08-14T11:37:10-03:00 | Fonte: F5.6 full 885/5 + quality/build/smoke verdes + dossiê ativo*
