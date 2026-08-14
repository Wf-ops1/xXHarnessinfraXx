# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.5](docs/tasks/active/F5.5.md): dossiê ativo, problema reproduzido, escopo e aceite congelados.
3. [F5.4](docs/tasks/completed/F5.4.md): orçamento promovido; reconciliação administrativa incorporada.
4. [F5.3](docs/tasks/completed/F5.3.md): trust boundary promovido e reconciliação incorporada.
5. [F5.2](docs/tasks/completed/F5.2.md): política unificada e promoção anterior comprovadas;
   checkpoint `checkpoint/f5.2-ready` somente local.
6. [F5.1 — resolver configuração no início da execução](docs/tasks/completed/F5.1.md): promoção
   anterior; checkpoints `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais.
7. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
8. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
9. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.5 — integrar secrets e redaction no caminho crítico |
| **Gate** | `READY / ACTIVE` |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-13T22:21:27-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.5-secrets-redaction`, local e sem upstream |
| **Baseline** | `main == origin/main == 2f4e391bfe3588f713a436b051d4f60e970e4df1` antes da branch |
| **Reconciliação F5.4** | PR [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), head `7613460`, merge `2f4e391bfe3588f713a436b051d4f60e970e4df1` |
| **CI final anterior** | run [31759971204](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31759971204), `push`, 11/11 success em 4m42s no baseline exato |
| **Problema F5.5** | multiline/contexto dinâmico, fallback de credencial OpenAI e `repr` Serena reproduzidos como vazamentos booleanos, sem expor valores |
| **Baseline focado** | R0 inválido por sandbox; R1 válido `230 passed, 3 skipped em 59.15s` |
| **Implementação local** | contexto imutável, provider/Serena/terminal/tool outcome redigidos; fallback secreto removido; matriz focada `192 passed, 3 skipped` |
| **Regressão integral** | `873 passed, 5 skipped, 6 subtests passed em 187.14s` |
| **Quality/build** | ruff, mypy, compileall, diff-check, wheel e smoke oficial offline verdes |
| **Checkpoint** | `checkpoint/f5.5-ready` no commit `16bcbb1`; COMPLETE ainda pendente, ambos somente locais |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.4 — integrar orçamento durável por execução e nó |
| Produto | commit `722916b`; certificação local `856 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), head final `21aa4a6`, CI `31739876952`, 11/11 success |
| Merge de produto | `d6246295045a156646af14de0011400feb6cb4f3`; CI de `push` `31742231398`, 11/11 success |
| Reconciliação administrativa | PR [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), head final `7613460`, merge `2f4e391bfe3588f713a436b051d4f60e970e4df1`; CI `31759971204`, 11/11 success em 4m42s |
| Fronteira | `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais; branches remotas preservadas; nenhuma tag/ref removida |
| Promoção anterior | F5.3 — trust boundary integrado: PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head `4934aee`, CI `31659293351`; merge `211edcf921912a32429934bf600473d8cc98941c`, pós-merge `31660030240`; reconciliação [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), merge/CI final `4c0527baacc74821112adf7fe61b82af72589f69` / `31728438719`; fronteira `default-restricted` e checkpoints `checkpoint/f5.3-ready`/`checkpoint/f5.3-complete` somente locais |
| Promoção F5.2 preservada | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. O gate F5.5 permite apenas o contexto imutável de secrets,
injeção por consumer autorizado, redaction de adapters/runtime/evidência, testes e documentação listados
em `docs/tasks/active/F5.5.md`. Dependências, lockfile, CI, versões, schemas e tarefas F5.6+ estão proibidos.

## 5. Tarefa ativa

A F5.5 está `READY / ACTIVE` em `docs/tasks/active/F5.5.md`. O baseline provou quatro lacunas sem
imprimir o valor usado: secret fragmentado e chamada sem contexto escapam do redator, o adapter OpenAI
legado lê o ambiente sem boundary e a configuração Serena expõe header sensível no `repr`. O escopo
congela resolução por nome/consumer, injeção somente no adapter, redaction antes de persistência e
truncamento, JSON estrutural, rotação por nova composição e ausência de secrets em prompts/journal.
A implementação corrigiu esses quatro pontos e passou o focado exato `192/3` e o full `873/5 + 6`;
quality integral, wheel e smoke isolado também passaram; restam o commit de produto e o checkpoint
COMPLETE locais.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. O R0 focado foi inválido somente porque o sandbox negou o temp/cache
do pytest; a repetição R1 passou `230 passed, 3 skipped`. A implementação local F5.5 está autorizada
depois do checkpoint READY. Push, PR, merge, publicação de tags, remoção de refs, force-push/bypass e
início da F5.6 não estão autorizados.

## 7. Próxima ação exata

```text
REVALIDAR DOCUMENTAÇÃO E O DIFF FINAL.
DEPOIS CRIAR O COMMIT LOCAL DE PRODUTO E `checkpoint/f5.5-complete`.
NÃO PUBLICAR, ABRIR PR, MESCLAR, PUBLICAR TAGS, REMOVER REFS OU INICIAR F5.6 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.5.md` e a Fase 5 do plano.
2. Confirme branch `task/f5.5-secrets-redaction`, baseline `2f4e391` e checkpoint `checkpoint/f5.5-ready`.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve os critérios congelados.
4. Não amplie arquivos/efeitos sem recongelar; push, PR, merge, tags/refs e F5.6 exigem nova autorização.

---

*Atualizado em: 2026-08-13T23:09:44-03:00 | Fonte: F5.5 + checkpoint 16bcbb1 + focado 192/3 + full 873/5/6 + wheel/smoke*
