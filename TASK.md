# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F3.7](docs/tasks/completed/F3.7.md): última implementação promovida, em reconciliação administrativa.
3. [F4.8](docs/tasks/completed/F4.8.md): fechamento anterior da Fase 4.
4. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
5. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership promovido.
6. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado; todas as tarefas F3/F4 e corretivas aplicáveis foram promovidas |
| **Fase ativa** | Pausa administrativa pós-F3.7; nenhuma implementação ativa |
| **Tarefa ativa** | nenhuma tarefa ativa; somente reconciliação documental da F3.7 |
| **Gate** | F3.7 `PROMOTED / ADMIN_PR_OPEN / CHECKS_PENDING`; merge administrativo não autorizado |
| **Executor ativo** | `Codex`, único escritor da reconciliação; publicação autorizada em `2026-08-12T12:49:18-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f3.7`, publicada em `origin/docs/promote-f3.7` e configurada como upstream |
| **Main certificada** | `main == origin/main == 10d75408f10ce83ffa232f117d203aa2f26bedb0` |
| **PR F3.7** | [#51](https://github.com/Wf-ops1/Harnessinfra/pull/51), head final `40f81375f93706352fd19b5ef280ebe674d5249d` |
| **PR administrativo** | [#52](https://github.com/Wf-ops1/Harnessinfra/pull/52), aberto não-draft; head inicial `639653532768b4b06eedc30045308923c83218d9` |
| **CI final do PR** | run [31568577459](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31568577459), 11/11 success |
| **CI pós-merge** | run [31568908128](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31568908128), 11/11 success no merge exato |
| **Checkpoints F3.7** | READY/COMPLETE de R0, R1 e R2 somente locais; nenhuma tag publicada |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **Próxima tarefa planejada** | F5.1 — resolver configuração no início da execução; ainda não autorizada |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F3.7 — promoção Git segura |
| Produto | `cb80f8b2d86b9ff38075e6f0068e32b62ba4dbb5`; R1/R2 alteraram somente testes |
| Pull request | PR #51; head final `40f81375`; run `31568577459`, 11/11 success |
| Promoção | merge `10d75408f10ce83ffa232f117d203aa2f26bedb0`; pós-merge `31568908128`, 11/11 success |
| Reconciliação | `ADMIN_PR_OPEN / CHECKS_PENDING` no PR #52; publicação inicial em `6396535`; gate documental pré-publicação `27 passed, 6 subtests passed` |
| Fronteira | branch de produto remota preservada; checkpoints somente locais; nenhuma tag/ref removida |

As falhas R0/R1 permanecem documentadas e perderam precedência somente após o R2 e as duas CIs finais
verdes. Nenhuma evidência negativa posterior foi observada. O atraso corrente é exclusivamente
documental e isolado pela DEC-014.

Evidência negativa nova sempre prevalece e exige correção sem relaxamento seguida de recertificação
integral antes de restaurar qualquer estado positivo.

## 5. Tarefa ativa

Não existe tarefa de implementação ativa. A F3.7 cria um candidate commit real no worktree F3.6,
exige aprovação `APPROVED` e a suíte integral no mesmo SHA, revalida branch/base/limpeza e promove
somente por `git cherry-pick <candidate_sha>`. Dry-run não altera o checkout; write-ahead, outcome e
recovery impedem repetição cega e SHA sintético/fallback.

O R1 e o R2 corrigiram premissas temporais somente nos testes: um cherry-pick byte-idêntico pode
legitimamente preservar o SHA. As provas passaram a observar diretamente exatamente uma operação
mutante, preservando parent, árvore, conteúdo, estado, eventos, aprovação e full suite commit-bound.

O head final recebeu 11/11 checks no PR e o merge exato recebeu 11/11 na CI de `push`. A F3.7 está
`PROMOTED`; a reconciliação exclusivamente documental foi publicada no PR #52 e aguarda checks no
head final.

## 6. Bloqueios atuais

Não há bloqueio técnico conhecido. A reconciliação está `ADMIN_PR_OPEN / CHECKS_PENDING`: todos os
checks do PR #52 precisam passar no head documental final. O merge administrativo exige nova autoridade
externa explícita. F5.1 não pode começar antes do fechamento desse PR, de sua CI pós-merge verde e de
nova autorização nominal.

Tag remota, exclusão de refs e início de outra tarefa não estão autorizados.

## 7. Próxima ação exata

```text
AUDITAR TODOS OS CHECKS DO PR ADMINISTRATIVO #52 NO HEAD DOCUMENTAL FINAL.
NÃO MESCLAR, CRIAR TAG, REMOVER REF OU INICIAR F5.1.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/completed/F3.7.md` integralmente.
2. Confirme branch `docs/promote-f3.7`, base `10d75408`, PR #52/head final e todos os seus checks;
   preserve como evidência o head inicial `6396535` e o PR de implementação #51/head `40f81375`.
3. Confirme que `docs/tasks/active/` contém apenas README e que o diff não toca produto/CI/dependências.
4. Execute somente a próxima ação exata; F5.1 continua planejada e não autorizada.

---

*Atualizado em: 2026-08-12T12:49:18-03:00 | Fonte: F3.7 + PRs #51/#52 + runs 31568577459/31568908128 + merge 10d75408 + DEC-014/015*
