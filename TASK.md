# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.5](docs/tasks/completed/F5.5.md): promoção no PR #61 e reconciliação administrativa local.
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
| **Tarefa ativa** | nenhuma implementação; F5.5 promovida e em reconciliação administrativa |
| **Gate** | nenhum gate `READY` ativo |
| **Estado corrente** | `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor autorizado em `2026-08-13T22:21:27-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f5.5`, publicada em `origin/docs/promote-f5.5` |
| **Checkpoint administrativo** | `73be828a6e4e813e9370eac7f4289179c7f05d79`, reconciliação local validada |
| **Branch de produto preservada** | `task/f5.5-secrets-redaction`, remota e não removida |
| **Main sincronizada** | `main == origin/main == 2227b73131d405cde046c58ec83094889a3feb51` antes da branch administrativa |
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
| **PR administrativo** | [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), head inicial `82f2395`, run inicial `31770610085` em andamento |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.5 — integrar secrets e redaction no caminho crítico |
| Produto | commit `f4460ad`; focado `192 passed, 3 skipped`; full `873 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#61](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61), head final `68482da`, CI `31765166979`, 11/11 success |
| Merge de produto | `2227b73131d405cde046c58ec83094889a3feb51`; CI de `push` `31769631054`, 11/11 success em 5m20s |
| Reconciliação administrativa | PR [#62](https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62), aberto no head inicial `82f2395`, checks pendentes |
| Fronteira | `checkpoint/f5.5-ready` e `checkpoint/f5.5-complete` somente locais; branch remota de produto preservada; nenhuma tag/ref removida |
| Promoção anterior | F5.4 — PR [#59](https://github.com/Wf-ops1/Harnessinfra/pull/59), produto `722916b`, head `21aa4a6`, CI `31739876952`; merge `d624629`, pós-merge `31742231398`; reconciliação [#60](https://github.com/Wf-ops1/Harnessinfra/pull/60), merge/CI final `2f4e391` / `31759971204`; certificação local `856 passed, 5 skipped, 6 subtests passed`; checkpoints `checkpoint/f5.4-ready` e `checkpoint/f5.4-complete` somente locais |
| Promoção anterior | F5.3 — trust boundary integrado: PR [#57](https://github.com/Wf-ops1/Harnessinfra/pull/57), head `4934aee`, CI `31659293351`; merge `211edcf921912a32429934bf600473d8cc98941c`, pós-merge `31660030240`; reconciliação [#58](https://github.com/Wf-ops1/Harnessinfra/pull/58), merge/CI final `4c0527baacc74821112adf7fe61b82af72589f69` / `31728438719`; fronteira `default-restricted` e checkpoints `checkpoint/f5.3-ready`/`checkpoint/f5.3-complete` somente locais |
| Promoção F5.2 preservada | PR [#55](https://github.com/Wf-ops1/Harnessinfra/pull/55), merge `df5fee5b97e4c0613327043a71bc665eacf46aa1`, pós-merge `31646282269`; reconciliação [#56](https://github.com/Wf-ops1/Harnessinfra/pull/56), merge/CI final `0607a0b385da1a864f629bf4811810a574d03768` / `31650131258` |
| Promoção F5.1 preservada | PR [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head `f42af27`, CI `31629604755`; merge `c46910e50ede1196c9beb1242cb7bd708905d666`, pós-merge `31630446370`; reconciliação [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge/CI final `fe95a91648a79c404565583c87c1cf357e8ab3a2` / `31633748837` |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A F5.5 está promovida; a branch atual permite somente a
reconciliação documental DEC-014 em `docs/tasks/completed/F5.5.md`. Produto, dependências, lockfile,
CI, versões, schemas e tarefas F5.6+ estão proibidos.

## 5. Tarefa ativa

Não há nenhuma tarefa ativa de implementação. A F5.5 está `PROMOTED` em
`docs/tasks/completed/F5.5.md`: o PR #61 passou
11/11 no head `68482da`, foi incorporado pelo merge commit `2227b73` e recebeu 11/11 na CI de `push`
`31769631054`. A branch administrativa local registra esses fatos sem iniciar F5.6.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A reconciliação administrativa está no PR #62 e aguarda os checks
do head final. Merge do PR administrativo, tags remotas, remoção de refs, force-push/bypass e início
da F5.6 não estão autorizados.

## 7. Próxima ação exata

```text
F5.5 ESTÁ PROMOVIDA; NÃO HÁ IMPLEMENTAÇÃO ATIVA.
PUBLICAR O REGISTRO DO PR #62 E AUDITAR TODOS OS CHECKS DO HEAD FINAL.
NÃO MESCLAR, REMOVER REFS, PUBLICAR TAGS OU INICIAR F5.6 POR INFERÊNCIA.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/completed/F5.5.md` e a DEC-014.
2. Confirme branch `docs/promote-f5.5`, `main == origin/main == 2227b73` e os checkpoints locais.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve os critérios congelados.
4. Não altere produto; publicação/PR/merge administrativos, tags/refs e F5.6 exigem nova autorização.

---

*Atualizado em: 2026-08-14T01:41:20-03:00 | Fonte: F5.5 + promoção 2227b73/31769631054 + PR administrativo #62/run inicial 31770610085*
