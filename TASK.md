# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F6.1](docs/tasks/completed/F6.1.md): schema único de eventos promovido pelo PR #69 no merge
   `7d6a0e1`, com CI pós-merge `31887143905` 11/11 verde; reconciliação administrativa no PR #70.
3. [F5.C1](docs/tasks/completed/F5.C1.md): corretiva promovida pelo PR #67 no merge `2b405fd`, com
   CI pós-merge `31857239235` 11/11 verde; reconciliação administrativa #68 incorporada em `29e8a975`,
   com CI pós-merge `31859624571` 11/11 verde.
4. [F5.7](docs/tasks/completed/F5.7.md): produto promovido no PR #65; reconciliação administrativa
   incorporada pelo PR #66 no merge `998a7ac`, com CI pós-merge `31849767573` 11/11 verde.
5. [F5.6](docs/tasks/completed/F5.6.md): produto promovido no PR #63; o snapshot administrativo
   incorporado por `docs/promote-f5.6` é complementado pela evidência externa posterior abaixo.
6. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa incorporada.
7. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
8. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
9. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
10. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
11. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
12. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 6.
13. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
    [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
    [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado; F5.1–F5.7, F5.C1 e F6.1 promovidas no produto |
| **Fase ativa** | nenhuma fase de implementação; reconciliação administrativa F6.1 em CI remota |
| **Tarefa ativa** | nenhuma tarefa ativa de implementação; PR administrativo #70 aberto |
| **Gate** | `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Estado corrente** | F6.1 `PROMOTED`; PR #70 aberto, checks do head final pendentes; F6.2 aguarda merge administrativo e CI pós-merge |
| **Estado F5.6** | F5.6 `PROMOTED`; aprovação de promoção permanece vinculada ao conteúdo exato |
| **Executor ativo** | nenhuma implementação ativa; `Codex` acompanha somente a reconciliação documental |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f6.1`, publicada e rastreando `origin/docs/promote-f6.1`; criada de `main == origin/main == 7d6a0e1` |
| **Branch de produto F6.1** | `task/f6.1-unified-event-schema`, remota e preservada após o merge |
| **Checkpoint F6.1** | `checkpoint/f6.1-ready` → `e149fb3`; R1 READY `eea6baa`; `checkpoint/f6.1-complete` histórico → `016f4ca`; `checkpoint/f6.1-r2-ready` → `3cb2a4b`; `checkpoint/f6.1-r2-complete` → `4785c22`; somente locais |
| **Checkpoint F5.C1** | `checkpoint/f5.c1-ready` antes da implementação; `checkpoint/f5.c1-complete` após a recertificação; ambos locais |
| **Checkpoint F5.7** | `checkpoint/f5.7-ready` em `527cb34`; `checkpoint/f5.7-r1-ready` em `c33b2f1`; `checkpoint/f5.7-complete` em `34fa3af`; `checkpoint/f5.7-r3-ready` em `d38311c`; somente locais |
| **Main sincronizada** | antes da branch administrativa, `origin/main == 7d6a0e179f30008a7a67275da94878a179f0aba9` |
| **Problema F6.1** | lacuna knowledge corrigida: aliases `*Event` são o único `ExecutionEvent`; dados registrados usam modelos `*Details` |
| **Baseline F6.1** | R0 inválido por temp bloqueado; R1 confinado `96 passed em 9.10s`; probe negativo reproduzível |
| **Produto F6.1** | `c9e41c4` — envelope único 2.0, `EventType` fechado, sequence sob lock, hash completo e metadados reais |
| **Correção F6.1 R1** | `c4aef27` — contratos knowledge reclassificados, aliases legados preservados e regressão estrutural ampliada |
| **Evidência F6.1 R2** | append aceitou draft mutado e o reload falhou por hash; `password: 1234`/`apiKey: false` ficaram visíveis; quatro refs canônicas históricas retornaram `ContractNotFoundError` |
| **Correção F6.1 R2** | `aa471d1` + `c9c5c83` — snapshot revalidado antes do hash, redaction fechada por semântica e quatro aliases qualificados restaurados |
| **Validação F6.1 R2** | probes `5 passed`; matriz ampliada `325 passed`; full `935 passed, 5 skipped, 6 subtests passed`; Ruff, mypy 107 arquivos, compileall, diff-check, wheel e smoke verdes |
| **PR F6.1** | [#69](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/69), head final `4c57a33e2df6ade006dffc184a5640298ae3a45a`; CI [31868906875](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31868906875) 11/11 success |
| **Merge F6.1** | `7d6a0e179f30008a7a67275da94878a179f0aba9`; CI pós-merge [31887143905](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31887143905) 11/11 success em 5m58s |
| **Reconciliação F6.1** | commit-base `45b7f033d0fdb5f73cb8e5bd82b718da07d5b4ce`; PR [#70](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/70), head inicial `aae1aea7120d68aec1ccf3861b609f1a3880590b`, CI inicial [31888260797](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31888260797) pendente |
| **Baseline focado F5.7** | R0 inválido por sandbox; R1 válido `90 passed, 2 skipped em 169.17s` |
| **Problema F5.7** | cancel só muda estado; terminal não recebe token; rollback promovido chama API legada desabilitada; `COMPLETED` não alcança rollback |
| **Produto F5.7** | R3 `26bb04d534dc8be5aae884f400d971ad66b6a9c1`; produto anterior `d787ce5f61f2e79415c76c06d928f030c026a4d8` preservado no histórico |
| **Implementação F5.7** | além do cancelamento/cleanup/revert canônicos, R3 confina ambiente/configuração Git, persiste aprovação de hook ligada à tentativa, retorna erro CLI em bloqueio e preserva ambiguidade sem reap comprovado |
| **Validação F5.7** | focado R3 `174 passed, 2 skipped`; segurança `68 passed`; full isolado `910 passed, 5 skipped, 6 subtests passed` |
| **Revisão R3** | quatro lacunas corrigidas e cobertas; a primeira full R3 foi inválida somente por `LOCALAPPDATA` bloqueado, e a repetição com `TEMP`/`TMP`/`LOCALAPPDATA`/basetemp externos passou integralmente |
| **Quality/distribuição F5.7** | mypy 106 arquivos, Ruff, compileall, diff-check, wheel 0.1.0 e smoke oficial offline com uv 0.12.3 verdes |
| **PR F5.7** | [#65](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/65), head final `b1cca81`, CI [31845896973](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31845896973) 11/11 success em 5m47s |
| **Merge F5.7** | `e8470ece8bdb7e98ddfe9817270d0b17032404d4`; CI pós-merge [31846634851](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31846634851) 11/11 success em 5m30s |
| **Reconciliação F5.7** | branch `docs/promote-f5.7`; PR [#66](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/66), head inicial `bb8d32e`, CI inicial `31848981895`, merge `998a7acaca46dc7f751798be4e2be9266d8028d1`; CI pós-merge [31849767573](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31849767573), 11/11 success |
| **Problema F5.C1** | `apiKey`/`deployToken`/`privateKey` atravessam config redaction; `password="valor com espaço"` atravessa `redact_text`; documentos descrevem estados anteriores |
| **Baseline F5.C1** | focado `263 passed, 2 skipped`; full `910 passed, 5 skipped, 6 subtests passed`; Ruff/mypy/diff verdes, mas evidência negativa posterior prevalece |
| **Produto F5.C1** | `ec8aa96` corrige as duas fronteiras; `5da7052` realinha documentos e testes de estado; nenhuma refatoração ampla |
| **Validação F5.C1** | probes redigidos; unidade `36 passed`; documentos `35 passed, 6 subtests`; F5 `267 passed, 2 skipped`; full `914 passed, 5 skipped, 6 subtests passed` |
| **Quality/distribuição F5.C1** | Ruff, mypy 106 arquivos, compileall, diff-check, wheel 0.1.0 e smoke oficial exato offline verdes |
| **PR F5.C1** | [#67](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/67), head final `3158d3b`; CI [31855763587](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31855763587) 11/11 success |
| **Merge F5.C1** | `2b405fdae5ea5560ce8e411297a0c11c4abc1bf9`; CI pós-merge [31857239235](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31857239235) 11/11 success |
| **Reconciliação F5.C1** | commit-base `7c41c520e11825c74cc8e95e9dd79c20532bc359`; PR [#68](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/68), CI inicial `31858431821`, head final `5b8e5585f2fd729787589feeb0ed9f4d217e6e7f`, 11 checks verdes; merge `29e8a9751c2cc1bf4e45fa530d971e969f22342f`; CI de push [31859624571](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31859624571), 11/11 success em 7m37s; encerramento terminal sem reconciliação recursiva |
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
| Tarefa | F6.1 — schema único de eventos |
| Produto | `c9e41c4`; correções R1 `c4aef27` e R2 `aa471d1`/`c9c5c83`; focado `325`; full `935 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#69](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/69), head final `4c57a33`, CI `31868906875`, 11/11 success |
| Merge de produto | `7d6a0e179f30008a7a67275da94878a179f0aba9`; CI de `push` `31887143905`, 11/11 success em 5m58s |
| Reconciliação administrativa | commit-base `45b7f03`; PR [#70](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/70), head inicial `aae1aea`, CI inicial `31888260797`, estado `ADMIN_PR_OPEN / CHECKS_PENDING` |
| Fronteira | nenhuma implementação ativa; F6.2 bloqueada até o PR administrativo e sua CI pós-merge ficarem verdes |
| Promoção anterior | F5.C1 — PR #67 / merge `2b405fd` / pós-merge `31857239235`; reconciliação PR #68 / merge `29e8a975` / pós-merge `31859624571` |
| Promoção anterior | F5.7 — cancelamento e rollback seguros: PR #65 / merge `e8470ec` / pós-merge `31846634851`; reconciliação PR #66 / merge `998a7ac` / pós-merge `31849767573` |
| Promoção anterior | F5.6 — PR [#63](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/63), merge `0488380`, pós-merge `31814250746`; reconciliação [#64](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/64), merge/CI final `a449bd1` / `31817497094` |
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

Não há executor de implementação ativo. O usuário autorizou criar e publicar `docs/promote-f6.1`,
atualizar a documentação, fazer commit, push e abrir o PR administrativo #70. O run inicial
`31888260797` foi identificado; `Codex` é o único escritor dessa reconciliação e seu merge não está
autorizado.

## 5. Tarefa ativa

Nenhuma tarefa de implementação está ativa. A F6.1 está `PROMOTED`; o estado histórico
`REPAIR_ACTIVE / PROMOTION_BLOCKED` permanece auditável e foi encerrado pela correção R2,
recertificação, PR #69, merge `7d6a0e1` e CI pós-merge `31887143905`. A reconciliação administrativa
está aberta no PR #70, com checks do head final pendentes. A F5.C1 permanece `PROMOTED`;
`POST_PROMOTION_BLOCKED / REPAIR_ACTIVE`
permanece como estado corretivo histórico daquela tarefa. F6.2–F6.7 não foram absorvidas nem iniciadas.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A branch foi publicada e o PR #70 foi aberto; mesclar esse PR,
iniciar F6.2, remover refs, publicar tags, usar force-push ou bypass continuam não autorizados.

## 7. Próxima ação exata

```text
PUBLICAR O REGISTRO DO PR #70 E ACOMPANHAR A CI DO NOVO HEAD FINAL.
APÓS 11/11 VERDES, PAUSAR PARA AUTORIZAÇÃO EXPLÍCITA DE MERGE COMMIT DO PR ADMINISTRATIVO.
NÃO MESCLAR O PR ADMINISTRATIVO, INICIAR F6.2, REMOVER REFS NEM PUBLICAR TAGS SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F6.1.md` e a Fase 6 do plano.
2. Confirme branch administrativa `docs/promote-f6.1`, upstream `origin/docs/promote-f6.1` e PR #70 aberto.
3. Preserve PR #68/merge `29e8a975`/CI `31859624571` como encerramento terminal da F5.C1.
4. Preserve `282`/`929` e `320`/`930` como históricos; a recertificação R2 vigente é `325`/`935`.
5. Preserve PR #69/head `4c57a33`/CI `31868906875`/merge `7d6a0e1`/pós-merge `31887143905`.
6. Preserve o head inicial `aae1aea` e a CI inicial `31888260797` do PR #70; valide a CI do head final.
7. Não mescle o PR administrativo, amplie para F6.2–F6.7, remova refs ou publique tags sem autorização.

---

*Atualizado em: 2026-08-15T10:50:16-03:00 | Fonte: PR #69 + merge `7d6a0e1` + CI `31887143905` + PR administrativo #70 + CI inicial `31888260797`*
