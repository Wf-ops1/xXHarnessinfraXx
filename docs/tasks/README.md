# Arquivo de tarefas e promoções

Este diretório separa o estado operacional corrente do histórico auditável. O painel atual permanece
em [`TASK.md`](../../TASK.md); requisitos normativos permanecem no
[`plano de implementação`](../plano_implementacao_harness_operacional.md).

## Como retomar

1. Leia integralmente `TASK.md`.
2. Leia o único dossiê apontado como ativo, quando houver.
3. Leia a fase ativa no plano principal.
4. Use este índice apenas para consultar evidência concluída; não recoloque histórico no painel.

## Convenções

- `active/`: no máximo um dossiê de execução, além do README do diretório.
- `completed/`: um arquivo imutável por tarefa/PR; correções exigem PR documental explícito.
- `migration-manifest.json`: origem e SHA-256 dos 19 payloads extraídos do painel legado.
- Git, PRs e runs de CI permanecem a evidência externa autoritativa de promoção.

## Tarefa ativa

A [F6.3 — gerar e validar o evidence manifest](active/F6.3.md) está `COMPLETED_LOCAL /
PROMOTION_PENDING` na branch local `task/f6.3-evidence-manifest`, derivada de
`main == origin/main == f5d2a33`. O checkpoint READY local aponta para `27a9f70`; o contrato,
storage atômico, terminalização e recovery passaram `7` testes dedicados, `253` focados e a full R2
com `965 passed, 5 skipped, 6 subtests passed`. Wheel e smoke oficial offline estão verdes.
O produto está commitado localmente em `0bf3a59`, e `checkpoint/f6.3-complete` aponta para esse SHA.
Push, PR, merge e publicação de tags não estão autorizados.

A [F6.2 — fortalecer o journal de auditoria](completed/F6.2.md) está terminalmente `PROMOTED`: o
head final `9fdd3cd` do [#71](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/71) passou 11/11 no run
`31899279536`, foi incorporado pelo merge `3f63428` e recebeu 11/11 na CI pós-merge `31899659117`
em 5m12s. A reconciliação [#72](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/72) encerrou no head
`d9e4010`, passou 11/11 no run `31901668046`, foi incorporada pelo merge `f5d2a33` e recebeu 11/11
na CI pós-merge `31902119059` em 5m02s. Pela DEC-014, esse fechamento é terminal.

A [F6.1 — schema único de eventos](completed/F6.1.md) está `PROMOTED`. O produto `c9e41c4`, a R1
`c4aef27` com `320` focados e `930` no full, e o estado histórico R2
`REPAIR_ACTIVE / PROMOTION_BLOCKED` permanecem auditáveis. As correções `aa471d1`/`c9c5c83`
eliminaram hash divergente após mutação de `details`, vazamento não textual e quatro refs knowledge
sem resolução. A recertificação passou `325` focados e `935 passed, 5 skipped, 6 subtests passed`;
o checkpoint local `checkpoint/f6.1-r2-complete` aponta para `4785c22`. O head final `4c57a33` do
[PR #69](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/69) passou 11/11 no run `31868906875`, foi
incorporado pelo merge `7d6a0e1` e recebeu 11/11 na CI pós-merge `31887143905` em 5m58s. A
reconciliação `docs/promote-f6.1`, cujo commit-base é `45b7f03`, foi incorporada pelo
[PR #70](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/70). O head inicial `aae1aea` abriu a CI
`31888260797`; o head final `9a346bd7` passou 11/11 no run `31888564163`, foi incorporado pelo merge
`ac887b0` e recebeu 11/11 na CI pós-merge `31888960272` em 5m29s. Pela DEC-014, esse fechamento é
terminal e não cria reconciliação recursiva.

A [F5.C1](completed/F5.C1.md) permanece `PROMOTED`: a corretiva localizada fechou as duas lacunas de
redaction, passou a recertificação integral e teve o head `3158d3b` incorporado pelo PR
[#67](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/67) no merge `2b405fd`. A CI do PR
`31855763587` e a CI pós-merge `31857239235` concluíram 11/11 verdes. A reconciliação administrativa
[#68](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/68) encerrou no head `5b8e558`, foi incorporada
no merge `29e8a975` e recebeu 11/11 na CI de push `31859624571`. Pela DEC-014, esse fechamento é
terminal e não abre reconciliação recursiva.

A [F5.7](completed/F5.7.md) permanece historicamente `PROMOTED`: o produto
R3 `26bb04d`, sobre o anterior `d787ce5`, persiste decisão/pedido de cancelamento, interrompe e reapera
a árvore vinculada, mantém cleanup explícito e executa `git revert` real do SHA canônico com conflito
em `BLOCKED_ROLLBACK`. O head final `b1cca81` passou 11/11 checks no run `31845896973` do PR #65,
foi incorporado pelo merge `e8470ec` e recebeu 11/11 na CI pós-merge `31846634851` em 5m30s. O focado
passou `174` testes com `2` skips, segurança passou `68` e a regressão integral isolada passou `910`
com `5` skips e `6` subtests; mypy, Ruff, compileall, diff-check, wheel e smoke oficial também ficaram
verdes. A reconciliação `docs/promote-f5.7` foi incorporada pelo PR #66 no merge `998a7ac`, e a CI
pós-merge `31849767573` concluiu 11/11 verde. Checkpoints permanecem locais; F6.1 e F6.2 foram
promovidas, e a reconciliação administrativa F6.2 encerrou terminalmente no merge `f5d2a33`.

A [F5.6](completed/F5.6.md) está `PROMOTED`: o PR #63 encerrou no head `6717f55`, passou 11/11 no
run `31813471013`, foi incorporado pelo merge `0488380` e recebeu 11/11 na CI pós-merge
`31814250746` em 10m34s. O produto é `7941dfe`; a matriz focada passou `47`, a regressão integral
passou `885`, com `5` skips e `6` subtests, e mypy, Ruff, compileall, diff-check, wheel e smoke oficial
com `uv 0.12.3` ficaram verdes. Os checkpoints READY `161e1c2` e COMPLETE `6717f55` permanecem
somente locais; branches remotas foram preservadas e nenhuma tag/ref foi removida. A reconciliação
administrativa PR #64 encerrou no head `7a1f6ed`, passou 11/11 no run `31816727870`, foi incorporada
pelo merge `a449bd1` e recebeu 11/11 na CI final `31817497094` em 6m15s. Esse fato externo posterior
complementa o snapshot interno `ADMIN_PR_OPEN / CHECKS_PENDING` sem criar reconciliação recursiva.

A [F5.5](completed/F5.5.md) está `PROMOTED`: o PR #61 encerrou no head `68482da`, passou 11/11 no
run `31765166979`, foi incorporado pelo merge `2227b73` e recebeu 11/11 na CI pós-merge
`31769631054` em 5m20s. A reconciliação administrativa PR #62 encerrou no head `45f4fb7`, passou
11/11 no run `31770761873`, foi incorporada pelo merge `daec37d` e recebeu 11/11 na CI final
`31771169636`.

A [F5.4](completed/F5.4.md) está `PROMOTED`: o PR #59 encerrou no head `21aa4a6`, passou 11/11 checks
no run `31739876952`, foi incorporado pelo merge `d624629` e recebeu 11/11 na CI pós-merge
`31742231398`. A reconciliação administrativa PR #60 encerrou no head `7613460`, foi incorporada pelo
merge `2f4e391` e recebeu 11/11 na CI final `31759971204` em 4m42s.

A [F5.3](completed/F5.3.md) está `PROMOTED`: o PR #57 encerrou no head `4934aee`, passou 11/11 checks
no run `31659293351`, foi incorporado pelo merge `211edcf` e recebeu 11/11 na CI pós-merge
`31660030240`. A reconciliação administrativa PR #58 encerrou no head `9d53e41`, passou 11/11 no run
`31727166976`, foi incorporada pelo merge `4c0527b` e recebeu 11/11 na CI final `31728438719`.

A [F5.2](completed/F5.2.md) permanece `PROMOTED`: o PR #55 encerrou no head `4dccce3`, passou 11/11
checks no run `31644174160`, foi incorporado pelo merge `df5fee5` e recebeu 11/11 na CI pós-merge
`31646282269`. A reconciliação administrativa PR #56 foi incorporada pelo merge `0607a0b`; a CI de
`push` final `31650131258` passou 11/11 no SHA exato.

A [F5.1](completed/F5.1.md) permanece `PROMOTED`: o PR #53 encerrou no head `f42af27`, passou 11/11
checks no run `31629604755`, foi incorporado pelo merge `c46910e` e recebeu 11/11 na CI pós-merge
`31630446370`. A reconciliação administrativa PR #54 foi incorporada pelo merge `fe95a91`; a CI de
`push` final `31633748837` passou 11/11 no SHA exato.

## Ledger concluído

| Fase | Tarefa | Dossiê | Promoção principal |
|---|---|---|---|
| F0 | F0.0 | [Preflight](completed/F0.0.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.1 | [Código bloqueante](completed/F0.1.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.2 | [Encoding](completed/F0.2.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.3 | [Ambiente reproduzível](completed/F0.3.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.4 | [Versionamento](completed/F0.4.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.5 | [Documentação honesta](completed/F0.5.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F0 | F0.6 | [CI mínima](completed/F0.6.md) | PR #1 / merge `3f29c4c` / pós-merge `30917066077` |
| F1 | F1.1 | [Schema do grafo](completed/F1.1.md) | PR #6 / merge `6c994b4` / pós-merge `31134295999` |
| F1 | F1.2 | [Registry de contratos](completed/F1.2.md) | PR #6 / merge `6c994b4` / pós-merge `31134295999` |
| F1 | F1.3 | [Policies e tools](completed/F1.3.md) | PR #6 / merge `6c994b4` / pós-merge `31134295999` |
| F1 | F1.4 | [Compilador único](completed/F1.4.md) | PR #6 / merge `6c994b4` / pós-merge `31134295999` |
| F1 | F1.5 | [Artefato determinístico](completed/F1.5.md) | PR #6 / merge `6c994b4` / pós-merge `31134295999` |
| F2 | F2.1 | [ExecutionRecord](completed/F2.1.md) | PR #7 / merge `34d00a5` / pós-merge `31142218012` |
| F2 | F2.2 | [Storage concorrente](completed/F2.2.md) | PR #8 / merge `b8307ca` / pós-merge `31148484495` |
| F2 | F2.3 | [Executor de grafo](completed/F2.3.md) | PR #9 / merge `60597c3` / pós-merge `31192555316` |
| F2 | F2.4 | [FSM por eventos](completed/F2.4.md) | PR #10 / merge `0579990` / pós-merge `31202447617` |
| F2 | F2.5 | [Retomada](completed/F2.5.md) | PR #11 / merge `2aa324b` / pós-merge `31209619778` |
| F2 | DOC-F2-STATUS | [Alinhamento público](completed/DOC-F2-STATUS.md) | PR #12 / merge `f23d74d` / pós-merge `31210521957` |
| F2 | F2.6 | [Retry com contexto](completed/F2.6.md) | PR #14 / merge `2dac824` / pós-merge `31215162155` |
| Governança | DOC-TASK-LEDGER | [Painel e arquivo](completed/DOC-TASK-LEDGER.md) | PR #16 / merge `fafbf62` / pós-merge `31218399437` |
| Governança | DOC-PROTOCOL-ALIGN | [Protocolo operacional](completed/DOC-PROTOCOL-ALIGN.md) | PR #19 / merge `1d08602` / pós-merge `31228310847` |
| F3 | F3.1 | [Provider real de modelo](completed/F3.1.md) | PR #20 / merge `acace94` / pós-merge `31230376744` |
| F3 | F3.2 | [Configuração e roteamento de modelos](completed/F3.2.md) | PR #21 / merge `3956f16` / pós-merge `31231730863` |
| F3 | F3.3 | [Loop de tool calls](completed/F3.3.md) | PR #22 / merge `0e64a88` / pós-merge `31232731611` |
| F3 | F3.C1 | [Integridade de modelo e model-turn](completed/F3.C1.md) | PR #23 / merge `5616fc5` / pós-merge `31240455344` |
| F3 | F3.C2 | [Execução durável de tools e policy](completed/F3.C2.md) | PR #24 / merge `d2502b0` / pós-merge `31266993044` |
| F3 | F3.4 | [Path guard](completed/F3.4.md) | PR #25 / merge `8fac2d0` / pós-merge `31272502445` |
| F3 | F3.6 | [Worktree Git externo](completed/F3.6.md) | PR #26 / merge `6757fbf` / pós-merge `31279967619` |
| F3 | F3.5 | [Terminal seguro por argv](completed/F3.5.md) | PR #27 / merge `b6a4a24` / pós-merge `31285547886` |
| F3 | F3.7 | [Promoção Git segura](completed/F3.7.md) | PR #51 / merge `10d75408` / pós-merge `31568908128`; administrativo #52 / merge `846c59e` / CI `31616226652` (`workflow_dispatch`) |
| F3 | F3.8 | [Edição real confinada e Serena MCP explícito](completed/F3.8.md) | PR #29 / merge `e6b5b84` / pós-merge `31295594376`; administrativo #30 / merge `c2aa89b` / pós-merge `31316853244` |
| F4 | F4.1 | [Armazenamento íntegro do índice estrutural](completed/F4.1.md) | PR #32 / merge `12ce3b7` / pós-merge `31323952381`; administrativo #33 / merge `571a8eb` / pós-merge `31329231458` |
| F4 | F4.2 | [Indexador Python AST commit-bound](completed/F4.2.md) | PR #34 / merge `212a9bf` / pós-merge `31345231098`; administrativo #35 / merge `3705693` / pós-merge `31346860397` |
| F4 | F4.3 | [Context sufficiency baseada em evidência](completed/F4.3.md) | PR #36 / merge `fa31ef8` / pós-merge `31419214233`; administrativo #37 / merge `5c8408d` / pós-merge `31433785637` |
| F4 | F4.4 | [Plano tipado e específico](completed/F4.4.md) | PR #38 / merge `93ce4ce` / pós-merge `31445624269`; administrativo #39 / merge `94641d2` / pós-merge `31447628152` |
| F4 | F4.C1 | [Imutabilidade concorrente da publicação de snapshots](completed/F4.C1.md) | PR #40 / merge `3905d02` / pós-merge `31453662008`; administrativo #41 / merge `362407f` / pós-merge `31455148050` |
| F4 | F4.5 | [Normalização fail-closed dos gates de verificação](completed/F4.5.md) | PR #42 / merge `4ae0de7` / pós-merge `31458482033`; administrativo #43 / merge `46b7070` / pós-merge `31459891130` |
| F4 | F4.6 | [Detecção de stack e resolução efetiva de comandos](completed/F4.6.md) | PR #44 / merge `a4fd1da` / pós-merge `31510277593`; administrativo #45 / merge `b578515` / pós-merge `31513097203` |
| F4 | F4.7 | [Persistência e guard canônico dos resultados de verificação](completed/F4.7.md) | PR #46 / merge `f7aa43a` / pós-merge falhou `31528955883`; corretivo #47 / merge `4aa701a` / pós-merge `31534918672`; administrativo #48 / merge `d4e34c7` / pós-merge `31541047111` |
| F4 | F4.8 | [Repair loop orientado pelos gates](completed/F4.8.md) | PR #49 / merge `72f89e3` / pós-merge `31551685950`; administrativo #50 / merge `9f75e35` / pós-merge `31557794240` |
| F5 | F5.1 | [Configuração efetiva no início da execução](completed/F5.1.md) | PR #53 / merge `c46910e` / pós-merge `31630446370`; administrativo #54 / merge `fe95a91` / pós-merge `31633748837` |
| F5 | F5.2 | [Política unificada de autorização de tools](completed/F5.2.md) | PR #55 / merge `df5fee5` / pós-merge `31646282269`; administrativo #56 / merge `0607a0b` / pós-merge `31650131258` |
| F5 | F5.3 | [Trust boundary integrado](completed/F5.3.md) | PR #57 / merge `211edcf` / pós-merge `31660030240`; administrativo #58 / merge `4c0527b` / pós-merge `31728438719` |
| F5 | F5.4 | [Orçamento durável por execução e nó](completed/F5.4.md) | PR #59 / merge `d624629` / pós-merge `31742231398`; administrativo #60 / merge `2f4e391` / pós-merge `31759971204` |
| F5 | F5.5 | [Secrets e redaction no caminho crítico](completed/F5.5.md) | PR #61 / merge `2227b73` / pós-merge `31769631054`; administrativo #62 / merge `daec37d` / pós-merge `31771169636` |
| F5 | F5.6 | [Aprovação vinculada ao conteúdo](completed/F5.6.md) | PR #63 / merge `0488380` / pós-merge `31814250746`; administrativo #64 / merge `a449bd1` / CI final `31817497094` |
| F5 | F5.7 | [Cancelamento e rollback seguros](completed/F5.7.md) | PR #65 / merge `e8470ec` / pós-merge `31846634851`; administrativo #66 / merge `998a7ac` / pós-merge `31849767573` |
| F5 | F5.C1 | [Hardening de redaction e realinhamento da Fase 5](completed/F5.C1.md) | PR #67 / merge `2b405fd` / pós-merge `31857239235`; administrativo #68 / merge `29e8a975` / CI final `31859624571` |
| F6 | F6.1 | [Schema único de eventos](completed/F6.1.md) | PR #69 / head `4c57a33` / merge `7d6a0e1` / pós-merge `31887143905`; administrativo #70 / inicial `aae1aea` / `31888260797`; final `9a346bd7` / `31888564163`; merge `ac887b0` / pós-merge `31888960272` |

Fechamentos documentais adicionais preservados no Git: PR #13 / merge `3596df3` / run
`31211290100` e PR #15 / merge `d48151b` / run `31215944126`.

## Decisões permanentes

| ID | Decisão resumida |
|---|---|
| DEC-001 | Gate de defensabilidade `READY` antes de implementação. |
| DEC-002 | `uv`, lockfile e Python `>=3.11,<3.15` como ambiente reproduzível. |
| DEC-003 | Versionamento separado para pacote, schemas e definições. |
| DEC-004 | Claims públicos classificados como implementados, experimentais ou planejados. |
| DEC-005 | `CI required` obrigatório e fail-closed em `main`. |
| DEC-006 | Capability declarada não implica adapter operacional; default-deny/deny-wins. |
| DEC-007 | `GraphCompiler` do pacote como pipeline único. |
| DEC-008 | Artefato 2.0 canônico, íntegro, versionado e publicado atomicamente. |
| DEC-009 | Uma branch e um PR por tarefa, partindo de `main` pós-merge verde. |
| DEC-010 | Painel curto; dossiê detalhado por tarefa; histórico concluído imutável e indexado. |
| DEC-011 | Regra histórica de certificação no gate seguinte, substituída pela reconciliação imediata da DEC-014. |
| DEC-012 | Realinhamento da Fase 3 em F3.C1/F3.C2, com pausa humana obrigatória e autorização nova entre tarefas. |
| DEC-013 | F3.4 cria guard parametrizado sem efeitos; F3.6 fornece worktree; F3.5/F3.8 integram consumidores depois de ambos. |
| DEC-014 | Reconciliação pós-merge imediata; evidência negativa prevalece e exige recertificação integral. |
| DEC-015 | Lifecycle possui a preparação F4; contexto bloqueia antes do grafo e verificação guarda `COMPLETED`. |
