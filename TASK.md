# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Dossiê ativo: [F4.5](docs/tasks/active/F4.5.md) — normalização fail-closed dos gates.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [Regras dos agentes](.agents/AGENTS.md): protocolo obrigatório de execução e Git.
5. [Índice histórico](docs/tasks/README.md): dossiês promovidos, PRs, merges e runs.

Em conflito: pedido explícito do usuário → plano principal → regras dos agentes → painel/dossiê, que
devem ser corrigidos para refletir a decisão. Nunca depender somente do histórico da conversa.

## 2. Invariantes operacionais

- um único executor/escritor por vez;
- nenhuma implementação sem problema comprovado, escopo/aceite congelados e gate `READY`;
- uma branch e um PR por tarefa, sempre a partir de `main` sincronizada e verde;
- nenhum merge antes de `CI required=success`; nenhuma tarefa seguinte antes da promoção completa;
- evidência negativa prevalece sobre sucesso anterior e bloqueia avanço até recertificação;
- estados positivos usam somente fatos observados; nenhum sucesso `0/0` ou sintético;
- paths e efeitos confinados; comandos por `argv` e `shell=False`;
- histórico concluído fica nos dossiês e no Git, não é duplicado neste painel.

## 3. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.4 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.5 — normalização fail-closed dos gates; F4.6+ e F3.7 não iniciadas |
| **Gate** | F4.5 `READY / ACTIVE`; checkpoint `checkpoint/f4.5-ready` antes do primeiro arquivo de produto |
| **Última promoção** | F4.C1 `PROMOTED`; PR administrativo #41 incorporado e CI pós-merge verde |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.5-normalize-gates`, criada do baseline promovido, sem upstream |
| **Baseline promovido** | `main == origin/main == 362407f`; run `31455148050`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Corretiva | F4.C1 corrigiu a publicação concorrente de snapshots e permanece `PROMOTED` |
| Implementação | PR #40 / merge `3905d02` / CI pós-merge `31453662008`, 11/11 |
| Reconciliação administrativa | PR #41 / merge `362407f4abd3aa98ae37278fb243d6eb73f11681` |
| CI administrativa | run `31455148050`, evento `push`, no SHA exato; 11/11 incluindo `CI required` |
| Fronteira | branches remotas preservadas; nenhuma tag publicada ou ref excluída |

O estado histórico `POST_PROMOTION_BLOCKED` da F4.1 foi encerrado pela F4.C1. Não resta blocker
técnico local da corretiva; o blocker corrente é o próprio aceite da F4.5 ainda em execução.

## 5. Tarefa ativa

A autorização nominal de `2026-08-11T00:31:23-03:00` iniciou a F4.5. A reprodução no baseline provou
que a policy usa `tests`, o evaluator usa `unit_test` e `GateRunner` aceita seleção vazia/desconhecida
como `all_passed=True` com `0/0`. O dossiê congelou os cinco IDs oficiais, rejeição antes de efeitos,
compatibilidade F4.3/F4.4, escopo e rollback. Nenhuma implementação de produto precede o checkpoint.

F4.5 não resolve stack/comandos F4.6, não persiste/guarda conclusão F4.7 e não cria retry F4.8.
F3.7 permanece depois da F4.7. Push, PR, merge, tag remota e exclusão de refs não estão autorizados.

## 6. Bloqueios atuais

O gate está `READY`, mas promoção permanece bloqueada até implementação e todos os critérios locais
do dossiê ficarem verdes. Falha posterior reabre imediatamente o gate. F4.6+ não podem iniciar.

## 7. Próxima ação exata

```text
CRIAR O CHECKPOINT LOCAL checkpoint/f4.5-ready E, SOMENTE DEPOIS, IMPLEMENTAR A NORMALIZAÇÃO
FAIL-CLOSED DENTRO DA ALLOWLIST. EXECUTAR TODO O ACEITE LOCAL E PARAR ANTES DE PUSH/PR/MERGE.
NÃO INICIAR F4.6+, F3.7, PUBLICAR TAG OU EXCLUIR REF.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.5.md` integralmente.
2. Leia DEC-015, as seções 1.1–1.2 e a Fase 4 do plano.
3. Confirme `.git`, branch, workspace, runtime, checkpoint e baseline `362407f`/run `31455148050`.
4. Execute somente a próxima ação exata. Divergência de escopo exige parar e recongelar.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- PR, CI, merge ou SHA só são registrados depois de observados;
- após gates locais, usar somente `COMPLETED_LOCAL / PROMOTION_PENDING` e aguardar autorização.

---

*Atualizado em: 2026-08-11T00:31:23-03:00 | Fonte: plano principal + DEC-014 + DEC-015*
