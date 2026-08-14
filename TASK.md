# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.7](docs/tasks/active/F5.7.md): produto concluído localmente; promoção ainda não autorizada.
3. [F5.6](docs/tasks/completed/F5.6.md): produto promovido no PR #63; o snapshot administrativo
   incorporado por `docs/promote-f5.6` é complementado pela evidência externa posterior abaixo.
4. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa incorporada.
5. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
6. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
7. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
8. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
9. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
10. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
11. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
    [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
    [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado; F5.1–F5.6 promovidas |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.7 — cancelamento e rollback seguros, promoção pendente |
| **Gate** | `COMPLETED_LOCAL / PROMOTION_PENDING` |
| **Estado corrente** | F5.6 `PROMOTED`; F5.7 implementada e certificada localmente, sem publicação |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-14T14:09:48-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.7-safe-cancel-rollback`, somente local e sem upstream |
| **Checkpoint F5.7** | `checkpoint/f5.7-ready` em `527cb34`; `checkpoint/f5.7-r1-ready` em `c33b2f1`; `checkpoint/f5.7-complete` será o commit documental final; somente locais |
| **Main sincronizada** | antes da branch, `main == origin/main == a449bd19b5f6535402535bc2815527a9689095dc`; origin confirmado por `ls-remote` |
| **Baseline focado F5.7** | R0 inválido por sandbox; R1 válido `90 passed, 2 skipped em 169.17s` |
| **Problema F5.7** | cancel só muda estado; terminal não recebe token; rollback promovido chama API legada desabilitada; `COMPLETED` não alcança rollback |
| **Produto F5.7** | `d787ce5f61f2e79415c76c06d928f030c026a4d8` |
| **Implementação F5.7** | decisão/pedido de cancelamento duráveis, árvore terminada/reapada, cleanup explícito, `git revert` canônico e conflito `BLOCKED_ROLLBACK` |
| **Validação F5.7** | focado `164 passed, 2 skipped`; segurança `68 passed`; full `900 passed, 5 skipped, 6 subtests passed` |
| **Quality/distribuição F5.7** | mypy 106 arquivos, Ruff, compileall, diff-check, wheel 0.1.0 e smoke oficial offline com uv 0.12.3 verdes |
| **Checkpoints F5.6** | `checkpoint/f5.6-ready` em `161e1c2`; `checkpoint/f5.6-complete` em `6717f55`; somente locais |
| **Produto F5.6** | `7941dfee0384927acdb5d94cd9e626194b7b1432` |
| **Problema F5.6** | JSON legado com 3 campos e subject imune a mudança de candidate reproduzidos por booleanos |
| **Implementação F5.6** | request canônico pós-candidate/gates, diff digest, decisão/expiração/invalidação journaled e guard pré-Git |
| **Matriz focada F5.6** | `47 passed em 187.74s`; node insuficiente, mismatch, expiry, tamper, CAS/recovery e Git real |
| **Regressão F5.6** | `885 passed, 5 skipped, 6 subtests passed em 557.95s` |
| **Quality/distribuição F5.6** | mypy 104 arquivos, Ruff, compileall, diff-check, wheel 0.1.0 e smoke oficial uv 0.12.3 verdes |
| **PR F5.6** | [#63](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/63), head final `6717f55`, CI [31813471013](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31813471013) 11/11 success |
| **Merge F5.6** | `048838076704fb852129b6ef76e9af6b7f878c35`; CI pós-merge [31814250746](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31814250746) 11/11 success em 10m34s |
| **Snapshot administrativo incorporado** | `ADMIN_PR_OPEN / CHECKS_PENDING` em `docs/promote-f5.6`; head inicial `e4a3178`, CI inicial `31816395182` |
| **Fechamento administrativo autoritativo** | PR [#64](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/64), head final `7a1f6ed84947f8bd3326aca70b3e8aeaaf761f24`, CI `31816727870` 11/11; merge `a449bd19b5f6535402535bc2815527a9689095dc`; CI final `31817497094` 11/11 em 6m15s |
| **Branch de produto preservada** | `task/f5.5-secrets-redaction`, remota e não removida |
| **Reconciliação F5.4** | PR [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), head `7613460`, merge `2f4e391bfe3588f713a436b051d4f60e970e4df1` |
| **CI final F5.4** | run [31759971204](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31759971204), `push`, 11/11 success em 4m42s |
| **Problema F5.5** | multiline/contexto dinâmico, fallback de credencial OpenAI e `repr` Serena reproduzidos como vazamentos booleanos, sem expor valores |
| **Baseline focado F5.5** | R0 inválido por sandbox; R1 válido `230 passed, 3 skipped em 59.15s` |
| **Implementação F5.5** | contexto imutável, provider/Serena/terminal/tool outcome redigidos; fallback secreto removido; matriz focada `192 passed, 3 skipped` |
| **Regressão F5.5** | `873 passed, 5 skipped, 6 subtests passed em 187.14s` |
| **Quality/build F5.5** | ruff, mypy, compileall, diff-check, wheel e smoke oficial offline verdes |
| **Produto F5.5** | commit local `f4460ad`; wheel e smoke reconstruídos após esse commit |
| **Checkpoint F5.5** | `checkpoint/f5.5-ready` no commit `16bcbb1`; `checkpoint/f5.5-complete` no commit documental de certificação, ambos somente locais |
| **PR F5.5** | [#61](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61), head final `68482da`, CI [31765166979](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31765166979) 11/11 success |
| **Merge F5.5** | `2227b73131d405cde046c58ec83094889a3feb51`; CI pós-merge [31769631054](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31769631054) 11/11 success em 5m20s |
| **PR administrativo F5.5** | [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), head final `45f4fb7`, CI `31770761873` 11/11; merge `daec37d119fced3a5e041c412ab01e7524c15800`, CI final `31771169636` 11/11 |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13; `uv`, `python` e `py` fora do `PATH` |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.6 — aprovação vinculada ao conteúdo |
| Produto | commit `7941dfe`; focado `47 passed`; full `885 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#63](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/63), head final `6717f55`, CI `31813471013`, 11/11 success |
| Merge de produto | `048838076704fb852129b6ef76e9af6b7f878c35`; CI de `push` `31814250746`, 11/11 success em 10m34s |
| Reconciliação administrativa | PR [#64](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/64), head final `7a1f6ed84947f8bd3326aca70b3e8aeaaf761f24`, CI `31816727870` 11/11; merge `a449bd19b5f6535402535bc2815527a9689095dc`; CI final `31817497094` 11/11 em 6m15s |
| Fronteira | `checkpoint/f5.6-ready` e `checkpoint/f5.6-complete` somente locais; branches remotas preservadas; nenhuma tag/ref removida |
| Promoção anterior | F5.5 — integrar secrets e redaction no caminho crítico: PR [#61](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61), head final `68482da`, CI `31765166979`; merge `2227b73`, pós-merge `31769631054`; reconciliação [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), merge/CI final `daec37d119fced3a5e041c412ab01e7524c15800` / `31771169636` |
| Promoção anterior | F5.4 — PR [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), produto `722916b`, head `21aa4a6`, CI `31739876952`; merge `d624629`, pós-merge `31742231398`; reconciliação [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), merge/CI final `2f4e391` / `31759971204`; certificação local `856 passed, 5 skipped, 6 subtests passed`; checkpoints `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais |
| Promoção anterior | F5.3 — trust boundary integrado: PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head `4934aee`, CI `31659293351`; merge `211edcf921912a32429934bf600473d8cc98941c`, pós-merge `31660030240`; reconciliação [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), merge/CI final `4c0527baacc74821112adf7fe61b82af72589f69` / `31728438719`; fronteira `default-restricted` e checkpoints `checkpoint/f5.3-ready`/`checkpoint/f5.3-complete` somente locais |
| Promoção F5.2 preservada | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

O snapshot administrativo incorporado não pode certificar o próprio merge posterior. A evidência
externa acima é autoritativa e encerra a cadeia sem reconciliação recursiva. Nova evidência negativa
prevalece sobre sucesso anterior e exige correção sem relaxamento, recertificação integral e
reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A autorização de implementação F5.7 foi consumida somente
na branch local. Produto, testes e certificação local estão concluídos; nenhum push, PR, merge ou tag
remota foi criado. Checkpoints F5.6 permanecem exclusivamente locais; branches
`task/f5.6-content-bound-approval` e `docs/promote-f5.6` estão preservadas no remoto.

## 5. Tarefa ativa

A F5.7 está concluída localmente no produto `d787ce5`. O controlador durável publica decisão e pedido
antes do sinal mesmo quando o executor detém o lock; após quiescência, o lifecycle reconcilia o
journal sob o lock canônico e só então apresenta `CANCELLED`. O terminal encerra e reapera a árvore
vinculada, o tool loop não persiste sucesso cancelado, cleanup permanece ação distinta e não forçada,
e rollback usa o SHA de promoção canônico em `git revert --no-edit`, verificando o novo SHA. Conflito
é abortado com segurança e termina em `BLOCKED_ROLLBACK`.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico local. O runtime `uv 0.12.3` já preservado foi usado somente no processo,
offline, sem instalação. Push da branch, PR, merge, tags remotas, remoção de refs,
force-push/bypass e início de F6 não estão autorizados.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL PARA PUBLICAR A BRANCH LOCAL.
NÃO CRIAR PR, TAG REMOTA OU MERGE E NÃO INICIAR F6.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.7.md` e a Fase 5 do plano.
2. Confirme branch `task/f5.7-safe-cancel-rollback` e produto `d787ce5` sobre baseline `a449bd1`.
3. Confirme os checkpoints locais `f5.7-ready`, `f5.7-r1-ready` e `f5.7-complete`.
4. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve o escopo/aceite certificado.
5. Não publique branch/PR/tags nem inicie F6 sem autorização nominal separada.

---

*Atualizado em: 2026-08-14T16:15:00-03:00 | Fonte: certificação local F5.7 + promoção F5.6/PR #64*
