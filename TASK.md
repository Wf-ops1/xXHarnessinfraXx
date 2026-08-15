# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.C1](docs/tasks/active/F5.C1.md): corretiva pós-promoção autorizada para dois vazamentos de
   redaction reproduzidos e para o realinhamento documental da Fase 5.
3. [F5.7](docs/tasks/completed/F5.7.md): produto promovido no PR #65; reconciliação administrativa
   incorporada pelo PR #66 no merge `998a7ac`, com CI pós-merge `31849767573` 11/11 verde.
4. [F5.6](docs/tasks/completed/F5.6.md): produto promovido no PR #63; o snapshot administrativo
   incorporado por `docs/promote-f5.6` é complementado pela evidência externa posterior abaixo.
5. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa incorporada.
6. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
7. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
8. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
9. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
10. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
11. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
12. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
    [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
    [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado; F5.1–F5.7 promovidas no produto |
| **Fase ativa** | Fase 5 — corretiva pós-promoção de redaction e documentação |
| **Tarefa ativa** | F5.C1 — hardening de redaction e realinhamento da Fase 5 |
| **Gate** | `READY / ACTIVE / POST_PROMOTION_BLOCKED / REPAIR_ACTIVE` |
| **Estado corrente** | F5.1–F5.7 historicamente `PROMOTED`; dois vazamentos reproduzidos bloqueiam o estado positivo corrente e F6 |
| **Estado F5.6** | F5.6 `PROMOTED`; aprovação de promoção permanece vinculada ao conteúdo exato |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-14T20:51:52-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.c1-redaction-alignment`, local e sem upstream |
| **Checkpoint F5.C1** | `checkpoint/f5.c1-ready`, local, antes da implementação |
| **Checkpoint F5.7** | `checkpoint/f5.7-ready` em `527cb34`; `checkpoint/f5.7-r1-ready` em `c33b2f1`; `checkpoint/f5.7-complete` em `34fa3af`; `checkpoint/f5.7-r3-ready` em `d38311c`; somente locais |
| **Main sincronizada** | antes da branch corretiva, `main == origin/main == 998a7acaca46dc7f751798be4e2be9266d8028d1` |
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
| Tarefa | F5.7 — cancelamento e rollback seguros |
| Produto | R3 `26bb04d`; head final `b1cca81`; focado `174 passed, 2 skipped`; full `910 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#65](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/65), head final `b1cca81`, CI `31845896973`, 11/11 success |
| Merge de produto | `e8470ece8bdb7e98ddfe9817270d0b17032404d4`; CI de `push` `31846634851`, 11/11 success em 5m30s |
| Reconciliação administrativa | PR [#66](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/66), merge `998a7ac`; CI pós-merge `31849767573`, 11/11 success |
| Fronteira | checkpoints F5.7 somente locais; branches preservadas; F6 bloqueada pela corretiva F5.C1, não pela reconciliação já encerrada |
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

Existe um único executor/escritor: `Codex`. O PR #65 foi incorporado às
`2026-08-14T19:26:38-03:00`; o CI pós-merge encerrou 11/11 verde às
`2026-08-14T19:32:11-03:00`. A reconciliação administrativa PR #66 foi incorporada pelo merge
`998a7ac` e recebeu 11/11 na CI pós-merge `31849767573`. Às
`2026-08-14T20:51:52-03:00`, o usuário autorizou a corretiva F5.C1 com `ajuste isso`.
Checkpoints F5.6 permanecem exclusivamente locais; branches
`task/f5.6-content-bound-approval` e `docs/promote-f5.6` estão preservadas no remoto.

## 5. Tarefa ativa

A F5.C1 está `READY / ACTIVE / POST_PROMOTION_BLOCKED / REPAIR_ACTIVE`. O produto F5.7 permanece
historicamente promovido, mas o gate positivo da Fase 5 foi reaberto pelas duas evidências negativas
de redaction. A implementação permitida é exclusivamente localizada e F6 permanece bloqueada.

## 6. Bloqueios e fronteiras externas

Há dois bloqueios técnicos reproduzidos e uma inconsistência documental, detalhados no dossiê F5.C1.
Não há bloqueio de ambiente. Push, PR, merge, tags remotas, remoção de refs, force-push/bypass e
início de F6 não estão autorizados por inferência.

## 7. Próxima ação exata

```text
CORRIGIR SOMENTE AS DUAS FRONTEIRAS DE REDACTION CONGELADAS NA F5.C1.
ADICIONAR SENTINELAS, REALINHAR OS DOCUMENTOS CORRENTES E RECERTIFICAR TODO O ACEITE.
NÃO PUBLICAR/ABRIR PR/MESCLAR NEM INICIAR F6 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.C1.md` e a Fase 5 do plano.
2. Confirme branch `task/f5.c1-redaction-alignment`, base `998a7ac` e checkpoint READY local.
3. Preserve PR #65/merge `e8470ec` e PR #66/merge `998a7ac`; evidência histórica não é reescrita.
4. Use exclusivamente `.\.venv\Scripts\python.exe` e não amplie o escopo congelado.
5. Não publique a branch, abra/mescle PR nem inicie F6 sem autorização nominal separada.

---

*Atualizado em: 2026-08-14T20:51:52-03:00 | Fonte: F5.C1 + baseline `998a7ac` + CI `31849767573` + evidências negativas reproduzidas*
