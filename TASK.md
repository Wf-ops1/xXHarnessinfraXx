# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é o gate [F4.4](docs/tasks/active/F4.4.md), com implementação local
   concluída, certificada e consolidada em commit local; a
   última promoção certificada permanece a [F4.3](docs/tasks/completed/F4.3.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.3 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.4 — plano tipado e específico; `COMPLETED_LOCAL / PROMOTION_PENDING` |
| **Gate** | F4.4 `READY` no checkpoint local `checkpoint/f4.4-ready` |
| **Última promoção** | F4.3 `PROMOTED`; PR administrativo #37 incorporado e CI pós-merge verde |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.4-typed-specific-plan`, criada de `origin/main`; sem upstream próprio ou publicação |
| **Baseline promovido** | `main == origin/main == 5c8408d`; run `31433785637`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.3` — context sufficiency baseada em evidência, promovida e arquivada localmente |
| PR de implementação | PR #36; head final `84eda1c421d13d1e8e86620127c3318e2cfe5086`; 11/11 no run `31414853048` |
| Promoção da implementação | merge `fa31ef8987b1028d38014fe676247cd425daf9b6`; run `31419214233`, 11/11 |
| Reconciliação administrativa | PR #37; head final `a7f7053e9783b5f6a9cbe43e922bf88dbe5c7443`; run `31430933615`, 11/11; merge `5c8408df9d1d1ce16d21508fbcb3a647ecf20ee1`; pós-merge `31433785637`, 11/11 |
| Fronteira | branches remotas preservadas; nenhuma tag remota ou exclusão de ref; F4.4 consolidada somente em commit local, sem push/PR; F3.7 não iniciada |

## 5. Tarefa ativa

O [gate F4.4](docs/tasks/active/F4.4.md) permanece `READY` e a implementação nominalmente autorizada
está concluída, certificada e consolidada no commit local desta branch. `PlanDocument` agora é Pydantic estrito/frozen/versionado;
`ModelRouter` roteia structured output pelas invariantes de egress/fallback/cancelamento/budget; o
lifecycle persiste `PLAN_GENERATION_STARTED`, payload/projeção e `PLAN_GENERATED` antes do primeiro nó.

Targets/critérios citam evidência relida por digest, gates/tools ficam limitados às policies
compiladas e resume em `PLANNING` recupera o mesmo plano sem nova chamada. Evento iniciado sem outcome,
payload/identidade divergente, policy ausente, plano inválido ou persistência falha bloqueiam em
`BLOCKED_PREREQUISITE`. FSM, `GraphExecutor`, record/bundle, defaults/policies, F4.5–F4.8 e F3.7
permaneceram fora do escopo; `checkpoint/f4.4-ready` continua anterior a todo hunk de produto.
F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há blocker técnico conhecido. Contrato, lifecycle, negativos, legado, documentação, regressão,
quality Windows/Linux, package/smoke e escopo passaram. O commit local de conclusão foi autorizado;
push, PR, merge, tag remota, exclusão de ref e qualquer F4.5+/F3.7 não foram autorizados.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL PARA PUBLICAR A BRANCH DA F4.4.
NÃO PUBLICAR BRANCH/TAG, ABRIR PR, FAZER MERGE, EXCLUIR REFS NEM INICIAR F4.5+/F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.4.md`, DEC-015, DEC-014, as seções 1.1–1.2 e a Fase 4 do plano integralmente.
3. Confirme F4.3 `PROMOTED`, PR #37, merge `5c8408d`, run `31433785637` e o checkpoint F4.4.
4. Confirme `.git`, `task/f4.4-typed-specific-plan`, `git status --short --branch`, `git log -10` e
   `main == origin/main == 5c8408d`.
5. Confirme o commit local F4.4 e execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T20:09:17-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
