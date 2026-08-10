# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é o gate [F4.3](docs/tasks/active/F4.3.md); a última promoção certificada
   continua sendo a [F4.2](docs/tasks/completed/F4.2.md).
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências das fases.
4. [Regras dos agentes](.agents/AGENTS.md): protocolo obrigatório de execução e Git.
5. [Índice histórico](docs/tasks/README.md): dossiês concluídos, PRs, merges e runs.

Em conflito: pedido explícito do usuário → plano principal → regras dos agentes → painel/dossiê, que
devem ser corrigidos para refletir a decisão. Nunca depender somente do histórico da conversa.

## 2. Invariantes operacionais

- um único executor/escritor por vez;
- nenhuma implementação sem problema comprovado, escopo/aceite congelados e gate `READY`;
- uma branch e um PR por tarefa, sempre a partir de `main` sincronizada e verde;
- nenhum merge antes de todos os checks do PR, incluindo `CI required`, terminarem verdes;
- nenhuma tarefa seguinte antes do merge anterior e da CI pós-merge verde em `main`;
- evidência negativa prevalece sobre sucesso anterior e bloqueia o próximo gate até recertificação;
- estados positivos usam somente fatos observados; atraso documental deve ser declarado como pendência;
- sem mocks ou sucesso sintético em produção; integração indisponível falha explicitamente;
- paths e efeitos confinados; comandos por `argv` e `shell=False`;
- secrets redigidos antes de persistência; estado necessário para retomar deve ser durável;
- histórico concluído fica nos dossiês e no Git, não é duplicado neste painel.

## 3. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.2 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | `F4.3` — implementação e aceitação local concluídas; PR #36 aberto, checks pendentes |
| **Gate** | F4.3 `READY` R5 / lifecycle `PR_OPEN / CHECKS_PENDING` |
| **Última promoção** | F4.2 `PROMOTED`; reconciliação administrativa encerrada pelo PR #35 |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.3-evidence-context-sufficiency`, publicada no origin; PR #36 aberto com head inicial `0cc4c38` |
| **Baseline promovido** | `main == origin/main == 3705693`; run `31346860397`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.2` — indexador Python AST local e vinculado ao commit, promovida e arquivada |
| PR de implementação | #34; head final `2268f3fa276b017ad5b64efdb54e7abbf1f917d9`; 11/11 no run `31344668587` |
| Promoção da implementação | merge `212a9bfba2189ce8ca84d8eca76ede2d872b7d2c`; run `31345231098`, 11/11 |
| Reconciliação administrativa | PR #35; head final `fffd226a0d5567daa2ef399f054c20704f2315ca`; merge `370569377a1b065db479c239edde4016e1de5c0a`; run pós-merge `31346860397`, 11/11 |
| Fronteira | branches remotas preservadas; nenhuma tag remota ou exclusão de ref; F4.3 aberta somente para preparar seu gate; F3.7 não iniciada |

## 5. Tarefa ativa

O [dossiê F4.3](docs/tasks/active/F4.3.md) preserva o checkpoint R1 e a auditoria que reabriu o gate:
score vazio `0.85`, evaluator parcial `1.0`, snapshot vazio aceito, gates `0/0` e CLI reprovada com exit
zero. A [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) corrige o blocker de ownership:
o lifecycle prepara contexto antes do grafo e persiste a transição bloqueante; F4.4–F4.8 possuem owners
explícitos e não podem terminar como componentes desconectados.

Após o checkpoint R4, contratos, policy, evaluator, assembler e lifecycle foram integrados dentro da
allowlist. O caminho compilado exige envelope imutável, persiste `CONTEXT_EVALUATED`, bloqueia antes do
primeiro nó, retoma por bundle, exaure após a tentativa inicial + duas retomadas e entrega somente
`graph_input` ao executor a partir de `PLANNING`. A regressão observada concluiu 673 testes, 2 skips
opt-in existentes e 6 subtests; build e smoke do wheel passaram. Planner, gates/verificação, repair,
F3.7, MCP e memória semântica continuam fora da implementação F4.3. F3.7 permanece depois da F4.7.

O R3 amplia exclusivamente a allowlist para a transição
`BLOCKED_INSUFFICIENT_CONTEXT → FAILED_RETRY_EXHAUSTED` e seu teste. Os checkpoints R1/R2 são
preservados, incluindo `checkpoint/f4.3-r2-ready`, e a autorização nominal inclui criar
`checkpoint/f4.3-r3-ready` e prosseguir com a
implementação depois dele.

O R4 permite exclusivamente que `GraphExecutor.execute()` aceite `PLANNING` como estado inicial
pré-grafo, além de `INITIATED`, sem alterar traversal, preflight ou resume. A tag
`checkpoint/f4.3-r4-ready` foi criada no commit `7bcc611` antes dessa alteração; a auditoria do diff
confirma somente essa exceção no executor.

O R5 foi autorizado nominalmente em `2026-08-10T12:54:21-03:00` para corrigir somente a
materialização de `affected_modules` em `runtime/planner.py:68` e seu teste/validação. Nenhum contrato
de plano, geração F4.4 ou outro comportamento do planner foi reaberto. O checkpoint
`checkpoint/f4.3-r5-ready` preservou toda a implementação R4 no commit `0c37602` antes dessa única
edição. A correção, o teste e a recertificação integral foram concluídos.

## 6. Bloqueios atuais

Não há blocker local aberto. `mypy src` e `mypy --platform linux src` passam nos 104 arquivos; os quatro
grupos congelados passam em 91/48/63/72 testes; a regressão integral concluiu 674 testes, 2 skips live
opt-in existentes e 6 subtests. Ruff, compileall, diff-check, build e smoke também estão verdes. Os
falsos sucessos de verificação continuam reservados para F4.5–F4.8. O PR #36 foi aberto contra `main`
com head inicial `0cc4c383ff024024242810dfff7961d495ce6ef6`. A primeira observação do run
`31409970887` encontrou 3/10 checks verdes e 7 em andamento, portanto o lifecycle é
`PR_OPEN / CHECKS_PENDING`. Tags permanecem somente locais; publicar tag, fazer merge ou excluir refs
continua não autorizado.

## 7. Próxima ação exata

```text
AGUARDAR TODOS OS CHECKS DO PR #36 TERMINAREM VERDES. NÃO PUBLICAR TAG, MESCLAR O PR, EXCLUIR REFS,
INICIAR F4.4/F3.7 OU ALTERAR A IMPLEMENTAÇÃO CONCLUÍDA SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.3.md`, DEC-015, `docs/tasks/completed/F4.2.md` e DEC-014 integralmente.
3. Confirme F4.3 `PR_OPEN / CHECKS_PENDING`, o PR #36, a branch e os cinco checkpoints locais.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e o baseline promovido da `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T13:39:00-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
