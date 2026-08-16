# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F6.4](docs/tasks/active/F6.4.md): PR #75 em reparo após a CI inicial revelar portabilidade Linux;
   R1 corrigida e certificada localmente, publicação autorizada.
3. [F6.3](docs/tasks/completed/F6.3.md): evidence manifest promovido pelo PR #73 no merge
   `1bd095a`; reconciliação #74 incorporada em `5b10b2d`, com CI pós-merge `31918043022` 11/11.
4. [F6.2](docs/tasks/completed/F6.2.md): hardening do journal promovido pelo PR #71 no merge
   `3f63428`; reconciliação PR #72 incorporada em `f5d2a33`, com CI pós-merge `31902119059` 11/11.
5. [F6.1](docs/tasks/completed/F6.1.md): schema único promovido; reconciliação PR #70 incorporada em
   `ac887b0`, com CI pós-merge `31888960272` 11/11 verde e encerramento terminal pela DEC-014.
6. [F5.C1](docs/tasks/completed/F5.C1.md): corretiva promovida pelo PR #67 no merge `2b405fd`, com
   CI pós-merge `31857239235` 11/11 verde; reconciliação administrativa #68 incorporada em `29e8a975`,
   com CI pós-merge `31859624571` 11/11 verde.
7. [F5.7](docs/tasks/completed/F5.7.md): produto promovido no PR #65; reconciliação administrativa
   incorporada pelo PR #66 no merge `998a7ac`, com CI pós-merge `31849767573` 11/11 verde.
8. [F5.6](docs/tasks/completed/F5.6.md): produto promovido no PR #63; o snapshot administrativo
   incorporado por `docs/promote-f5.6` é complementado pela evidência externa posterior abaixo.
9. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa incorporada.
10. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
11. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
12. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
13. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
14. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
15. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 6.
16. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
    [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
    [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado; F5.1–F5.7, F5.C1 e F6.1–F6.3 promovidas no produto |
| **Fase ativa** | Fase 6; F6.4 — implementar um doctor real |
| **Tarefa ativa** | [F6.4](docs/tasks/active/F6.4.md); R1 Linux localmente verde, commit/push corretivos pendentes |
| **Gate** | `COMPLETED_LOCAL / REPAIR_ACTIVE / PROMOTION_BLOCKED` |
| **Estado corrente** | PR #75 aberto; CI inicial falhou nos dois Tests Ubuntu; correção preserva launcher da virtualenv e está recertificada |
| **Estado F5.6** | F5.6 `PROMOTED`; aprovação de promoção permanece vinculada ao conteúdo exato |
| **Executor ativo** | `Codex`, único escritor autorizado da implementação local F6.4 |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f6.4-real-doctor`, com upstream `origin/task/f6.4-real-doctor`; criada de `main == origin/main == 5b10b2d` |
| **Branch de produto F6.3** | `task/f6.3-evidence-manifest`, remota e preservada após o merge |
| **Branch de produto F6.2** | `task/f6.2-harden-journal`, remota e preservada após o merge |
| **Branch de produto F6.1** | `task/f6.1-unified-event-schema`, remota e preservada após o merge |
| **Checkpoint F6.1** | `checkpoint/f6.1-ready` → `e149fb3`; R1 READY `eea6baa`; `checkpoint/f6.1-complete` histórico → `016f4ca`; `checkpoint/f6.1-r2-ready` → `3cb2a4b`; `checkpoint/f6.1-r2-complete` → `4785c22`; somente locais |
| **Checkpoint F5.C1** | `checkpoint/f5.c1-ready` antes da implementação; `checkpoint/f5.c1-complete` após a recertificação; ambos locais |
| **Checkpoint F5.7** | `checkpoint/f5.7-ready` em `527cb34`; `checkpoint/f5.7-r1-ready` em `c33b2f1`; `checkpoint/f5.7-complete` em `34fa3af`; `checkpoint/f5.7-r3-ready` em `d38311c`; somente locais |
| **Checkpoint F6.2** | `checkpoint/f6.2-ready` → `fb9909d2d3b3941251a521a3595f3d62ee3d3c0d`; `checkpoint/f6.2-complete` → `63e5091fd5cb68a527003d632b82d2dc6ee87074`; ambos somente locais |
| **Checkpoint F6.3** | `checkpoint/f6.3-ready` → `27a9f7057e05d6128ed21f7a5c5c463494749f04`; `checkpoint/f6.3-complete` → `0bf3a5910a768fd199130ebea0377911f24e4e55`; ambos somente locais |
| **Checkpoint F6.4** | `checkpoint/f6.4-ready` → `261f0977f9d0ed16ac51ce569b631a43ae7e49ff`; `checkpoint/f6.4-complete` → `0088b3149f559b77a9a0336cd73d4f2a3b7adccb`; ambos somente locais e imutáveis |
| **Main sincronizada** | antes da branch F6.4, `main == origin/main == 5b10b2d453768de62e9f64ae6d0095cfcd95cd03` |
| **Problema F6.4** | `HealthProbe` fabrica seis `OK`; doctor retorna zero com Git fora do `PATH`; `--json` e `--workflow` não existem |
| **Baseline F6.4** | probe negativo `doctor=0`, `--json=2`, `--workflow=2`; matriz vigente `9 passed in 18.78s` |
| **Implementação F6.4** | seis estágios estritos sobre Git, Python, provider, MCP, storage, worktree e gates; config canônica, transporte read-only, redaction, JSON determinístico, `--workflow` e exit code não zero quando unhealthy |
| **Validação F6.4** | dedicado `23 passed in 1.69s`; documentos `31 passed in 3.58s`; focado R2 `282 passed, 2 skipped, 6 subtests passed in 173.70s`; full R2 `990 passed, 5 skipped, 6 subtests passed in 937.00s`; Ruff, mypy 110 arquivos, compileall, diff-check, wheel R2 e smoke offline verdes |
| **PR F6.4** | [#75](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/75), head inicial `0088b3149f559b77a9a0336cd73d4f2a3b7adccb`, mergeável |
| **CI inicial F6.4** | run [31923378762](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31923378762): 8/10 jobs obrigatórios verdes; Tests Ubuntu 3.11/3.14 falharam em `PYTHON_IMPORT_SMOKE_FAILED`; `CI required` bloqueou corretamente |
| **Correção F6.4 R1** | preserva `.venv/bin/python` para execução e usa o alvo resolvido somente para validação; regressão determinística cobre launcher/alvo distintos |
| **Validação F6.4 R1** | dedicado `24 passed in 2.13s`; full `991 passed, 5 skipped, 6 subtests passed in 371.40s`; Ruff, mypy 110 arquivos, compileall e diff-check verdes |
| **Gate F6.4** | `COMPLETED_LOCAL / REPAIR_ACTIVE / PROMOTION_BLOCKED`; R1 local verde, promoção depende da CI do head corretivo |
| **Problema F6.3** | dois caminhos saltam diretamente para `COMPLETED`; `GENERATING_EVIDENCE` não é usado e `evidence.json` não possui producer/validator |
| **Baseline F6.3** | tentativa R0 inválida por diretório externo ausente; probe R1 válido `2 passed in 5.44s`; matriz confinada `127 passed in 34.85s` |
| **Implementação F6.3** | contrato estrito/canônico; publicação imutável e atômica; agregação redigida; `VERIFYING`/`PROMOTING` → `GENERATING_EVIDENCE` → `COMPLETED`; recovery terminal idempotente e fail-closed |
| **Validação F6.3** | dedicado `7 passed in 6.56s`; recovery R2 `35 passed in 30.29s`; focado R2 `253 passed in 188.59s`; full R2 `965 passed, 5 skipped, 6 subtests passed in 404.00s`; Ruff, mypy 109 arquivos, compileall, diff-check, sdist/wheel e smoke oficial offline verdes |
| **Recertificação de promoção F6.3** | focado atual `205 passed in 59.59s`; full atual `965 passed, 5 skipped in 794.91s`; Ruff, mypy 109 arquivos, compileall e diff-check verdes |
| **PR F6.3** | [#73](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/73), head final `ed1f0e0ab025255a4249db1f0929d4c9e3e7fc23`; CI [31913438082](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31913438082) 11/11 success em 6m57s |
| **Merge F6.3** | `1bd095a8f7c474b554a0a0cbd0a2be62448dc9b3`; CI pós-merge [31913877551](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31913877551) 11/11 success em 5m39s |
| **Reconciliação F6.3** | PR [#74](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/74), head inicial `c92597111f0c9ad11c01360f0348357c2fe379b2`; head final `e557d46c2d3f9848ab39c289f9ace4f3c959b11c`; CI `31916987572` 11/11; merge `5b10b2d453768de62e9f64ae6d0095cfcd95cd03`; CI pós-merge `31918043022` 11/11; encerramento terminal |
| **Problema F6.2** | manager legado e storage canônico escrevem schemas distintos no mesmo journal; `execution_id` ausente, append sem lock e corrupção gera erro cru |
| **Baseline F6.2** | probe determinístico reproduziu quebra entre duas instâncias; matriz confinada `127 passed in 19.84s` |
| **Implementação F6.2** | manager delega append/read ao storage canônico; erros audit tipados; checkpoint local/HMAC-SHA256 opcional; JSON/SARIF fail-closed; CLI preserva export sem reflow |
| **Validação F6.2** | dedicado `17 passed in 7.26s`; corrida concorrente `20/20`; focado `146 passed in 27.87s`; full `954 passed, 5 skipped, 6 subtests passed in 471.73s`; Ruff, mypy 107 arquivos, compileall, diff-check, wheel e smoke verdes |
| **PR F6.2** | [#71](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/71), head final `9fdd3cde2accfd40211252ab884b7f1091f341ce`; CI [31899279536](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31899279536) 11/11 success |
| **Merge F6.2** | `3f63428fba6223b8cb4a96f35fae609fbfffaa7f`; CI pós-merge [31899659117](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31899659117) 11/11 success em 5m12s |
| **Reconciliação F6.2** | commit-base `674cd9a4c9970f34394dfbd7a6ef677057245fc4`; PR [#72](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/72), CI inicial `31901521807`, head final `d9e4010cc178b61a95754a0b4266c40d4a309638`, CI [31901668046](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31901668046) 11/11; merge `f5d2a3372a630d3ca1dabee1b02465fbde8da87d`; CI pós-merge [31902119059](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31902119059) 11/11 success em 5m02s; encerramento terminal |
| **Problema F6.1** | lacuna knowledge corrigida: aliases `*Event` são o único `ExecutionEvent`; dados registrados usam modelos `*Details` |
| **Baseline F6.1** | R0 inválido por temp bloqueado; R1 confinado `96 passed em 9.10s`; probe negativo reproduzível |
| **Produto F6.1** | `c9e41c4` — envelope único 2.0, `EventType` fechado, sequence sob lock, hash completo e metadados reais |
| **Correção F6.1 R1** | `c4aef27` — contratos knowledge reclassificados, aliases legados preservados e regressão estrutural ampliada |
| **Evidência F6.1 R2** | append aceitou draft mutado e o reload falhou por hash; `password: 1234`/`apiKey: false` ficaram visíveis; quatro refs canônicas históricas retornaram `ContractNotFoundError` |
| **Correção F6.1 R2** | `aa471d1` + `c9c5c83` — snapshot revalidado antes do hash, redaction fechada por semântica e quatro aliases qualificados restaurados |
| **Validação F6.1 R2** | probes `5 passed`; matriz ampliada `325 passed`; full `935 passed, 5 skipped, 6 subtests passed`; Ruff, mypy 107 arquivos, compileall, diff-check, wheel e smoke verdes |
| **PR F6.1** | [#69](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/69), head final `4c57a33e2df6ade006dffc184a5640298ae3a45a`; CI [31868906875](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31868906875) 11/11 success |
| **Merge F6.1** | `7d6a0e179f30008a7a67275da94878a179f0aba9`; CI pós-merge [31887143905](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31887143905) 11/11 success em 5m58s |
| **Reconciliação F6.1** | branch `docs/promote-f6.1`; commit-base `45b7f033d0fdb5f73cb8e5bd82b718da07d5b4ce`; PR [#70](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/70), head inicial `aae1aea7120d68aec1ccf3861b609f1a3880590b`, CI inicial [31888260797](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31888260797); head final `9a346bd7f10f221989219979d2b66e6957cf093e`, CI `31888564163` 11/11; merge `ac887b055959d9d2c0c43b9b57df33e0d1eb9378`, CI pós-merge [31888960272](https://github.com/Wf-ops1/xXHarnessinfraXx/actions/runs/31888960272) 11/11 success em 5m29s; encerramento terminal |
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
| Tarefa | F6.3 — gerar e validar o evidence manifest |
| Produto | `0bf3a59`; dedicado `7`; recovery `35`; focado `253`; full `965 passed, 5 skipped, 6 subtests passed`; quality, wheel e smoke verdes |
| PR de produto | [#73](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/73), head final `ed1f0e0`, CI `31913438082`, 11/11 success em 6m57s |
| Merge de produto | `1bd095a8f7c474b554a0a0cbd0a2be62448dc9b3`; CI de `push` `31913877551`, 11/11 success em 5m39s |
| Reconciliação administrativa | PR [#74](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/74), head final `e557d46`, CI `31916987572` 11/11; merge `5b10b2d`; pós-merge `31918043022` 11/11 |
| Fronteira | cadeia F6.3 terminal; PR #75 bloqueado pela CI inicial, R1 local pronta para publicação autorizada |
| Promoção anterior | F6.2 — PR #71 / merge `3f63428` / pós-merge `31899659117`; reconciliação PR #72 / merge `f5d2a33` / pós-merge `31902119059` |
| Promoção anterior | F6.1 — PR #69 / merge `7d6a0e1` / pós-merge `31887143905`; reconciliação PR #70 / merge `ac887b0` / pós-merge `31888960272` |
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

As autorizações de implementação, publicação, merge e reconciliação F6.2 foram consumidas e a cadeia
encerrou terminalmente no merge `f5d2a33`/CI `31902119059`. Em `2026-08-15T16:03:17-03:00`, o usuário
autorizou revisar e preparar o gate F6.3. Em `2026-08-15T16:13:17-03:00`, autorizou também a
implementação local no escopo congelado. Em `2026-08-15T17:12:55-03:00`, produto e certificação
local foram concluídos. Em `2026-08-15T17:57:20-03:00`, a autorização seguinte foi consumida para
criar o commit de produto `0bf3a59` e o checkpoint local `checkpoint/f6.3-complete`. Em
`2026-08-15T19:53:08-03:00`, a autorização nominal de continuação foi consumida no push sem force e
na abertura do PR #73 contra `main`. Em `2026-08-15T20:06:32-03:00`, a autorização nominal de merge
foi consumida no merge commit `1bd095a`; a CI pós-merge `31913877551` passou 11/11 em 5m39s. Em
`2026-08-15T21:17:21-03:00`, as autorizações nominais de publicação e confirmação final foram
consumidas no push sem force e na abertura do PR administrativo #74 contra `main`. O head inicial é
`c925971` e a CI inicial `31916819934` disparou 10 checks. Autorizações posteriores foram consumidas
no head final `e557d46`, CI `31916987572` 11/11, merge `5b10b2d` e CI pós-merge `31918043022` 11/11.
Em `2026-08-15T22:15:52-03:00`, o usuário autorizou preparar o gate F6.4. Autorizações explícitas
posteriores nesta tarefa foram consumidas somente para a implementação local no escopo congelado. Em
`2026-08-15T23:31:55-03:00`, produto e certificação R2 foram concluídos. Em
`2026-08-15T23:45:41-03:00`, a autorização seguinte foi consumida somente para criar o commit local e
`checkpoint/f6.4-complete`; publicação, PR, merge, tags remotas e remoção de refs não estão
autorizados. Autorizações nominais posteriores foram consumidas no push sem force e na abertura do
PR #75 no head inicial `0088b31`. O run `31923378762` falhou nos dois Tests Ubuntu e reabriu o gate.
Em `2026-08-16T01:58:36-03:00`, o usuário autorizou a correção R1, recertificação, commit e atualização
sem force do mesmo PR; merge, tags remotas e remoção de refs permanecem não autorizados.

## 5. Tarefa ativa

A [F6.4](docs/tasks/active/F6.4.md) está `COMPLETED_LOCAL / REPAIR_ACTIVE / PROMOTION_BLOCKED`: a CI
inicial do PR #75 revelou a perda do launcher da virtualenv no Linux. A R1 foi corrigida e passou
`24` dedicados e full `991 passed, 5 skipped, 6 subtests passed`; commit/push corretivos são a próxima
ação. A F6.3 e sua reconciliação administrativa estão terminalmente promovidas. F6.5–F6.7 não foram iniciadas;
`POST_PROMOTION_BLOCKED / REPAIR_ACTIVE` é apenas estado corretivo histórico da F5.C1.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico local conhecido. A promoção permanece bloqueada até o commit R1 ser publicado
sem force e a CI do head exato ficar verde. Merge, force/bypass, tags remotas e remoção de refs
continuam fora do escopo.

## 7. Próxima ação exata

```text
CRIAR COMMIT CORRETIVO R1 E PUBLICAR SEM FORCE NO PR #75.
ACOMPANHAR A CI DO HEAD EXATO ATÉ ESTADO TERMINAL; NÃO MESCLAR.
NÃO MOVER/PUBLICAR TAGS, USAR FORCE/BYPASS OU REMOVER REFS.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F6.4.md` e a Fase 6 do plano.
2. Confirme `task/f6.4-real-doctor` com upstream homônimo e PR #75, derivada de `5b10b2d`.
3. Preserve PR #68/merge `29e8a975`/CI `31859624571` como encerramento terminal da F5.C1.
4. Preserve `282`/`929` e `320`/`930` como históricos; a recertificação R2 vigente é `325`/`935`.
5. Preserve PR #69/head `4c57a33`/CI `31868906875`/merge `7d6a0e1`/pós-merge `31887143905`.
6. Preserve PR #70: inicial `aae1aea`/`31888260797`; final `9a346bd7`/`31888564163`; merge
   `ac887b0`; pós-merge `31888960272`.
7. Preserve PR #71/head `9fdd3cd`/CI `31899279536`/merge `3f63428`/pós-merge `31899659117`.
8. Preserve PR #72/head `d9e4010`/CI `31901668046`/merge `f5d2a33`/pós-merge `31902119059` como
   encerramento terminal da F6.2.
9. Preserve PR #73/head `ed1f0e0`/CI `31913438082`/merge `1bd095a`/pós-merge `31913877551` e PR #74:
   head final `e557d46`/CI `31916987572`/merge `5b10b2d`/pós-merge `31918043022`.
10. Preserve `checkpoint/f6.4-complete` em `0088b31` e a evidência inicial R2 `282`/`990`.
11. Preserve run `31923378762` como evidência negativa; a R1 vigente é dedicado `24` e full `991`.
12. Publique somente o commit R1 sem force e não mescle sem autorização nominal posterior.

---

*Atualizado em: 2026-08-16T02:10:35-03:00 | Fonte: CI inicial PR #75 + correção F6.4 R1 local*
