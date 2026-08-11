# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não existe nenhuma tarefa ativa de implementação. A [F4.5](docs/tasks/completed/F4.5.md) foi promovida e
   está em reconciliação administrativa local.
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.5 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | nenhuma implementação ativa; PR administrativo F4.5 #43 aberto; F4.6+ e F3.7 não iniciadas |
| **Gate** | F4.5 `PROMOTED`; PR #43 em `ADMIN_PR_OPEN / CHECKS_PENDING`; checkpoint `checkpoint/f4.5-ready` |
| **Última promoção** | F4.5 `PROMOTED`; PR #42 incorporado e CI pós-merge verde no SHA exato |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.5`, rastreando `origin/docs/promote-f4.5`; PR #43; head inicial `b304164` |
| **Baseline promovido** | `main == origin/main == 4ae0de7`; run `31458482033`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **Promoção F4.5** | head final `9e8dfe8`; PR CI `31457935429`; merge `4ae0de7`; pós-merge `31458482033`, todos 11/11 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | F4.5 — taxonomia canônica e gates fail-closed, promovida e arquivada localmente |
| PR de implementação | PR #42; head final `9e8dfe80a8aaf0bcf4180866fb6e40eb117b0fc6`; run `31457935429`, 11/11 |
| Promoção | merge `4ae0de798607cf4fec13c0469fddb93d8024ead5`; run `31458482033`, 11/11 |
| Reconciliação administrativa | PR #43 aberto no head inicial `b304164`; run inicial `31459427729` em andamento |
| Fronteira | branch remota de implementação preservada; nenhuma tag publicada ou ref excluída |

O estado histórico `POST_PROMOTION_BLOCKED` da F4.1 foi encerrado pela F4.C1. Não resta blocker
técnico conhecido na F4.5; o blocker corrente é somente sua reconciliação administrativa obrigatória.

## 5. Tarefa ativa

Não existe nenhuma tarefa ativa de implementação. A [F4.5](docs/tasks/completed/F4.5.md) centraliza os cinco IDs
oficiais, substitui `tests` por `unit_test` e rejeita policy/suíte vazia, desconhecida, duplicada ou
sem comando antes de qualquer subprocesso. Nenhuma implementação precedeu o checkpoint.

Aceite observado: 64 testes focados, 79 de compatibilidade, 25 documentais + 6 subtests, regressão
integral de `714 passed, 2 skipped, 6 subtests passed`, mypy Windows/Linux em 105 arquivos, Ruff,
compileall, diff, build isolado e smoke da wheel verdes. Escopo proibido permaneceu byte-idêntico.

O head final `9e8dfe8` recebeu 11/11 checks no run `31457935429`. O merge `4ae0de7` recebeu 11/11 na
CI de `push` `31458482033`. A pausa corrente é exclusivamente administrativa: o PR #43 está aberto
e precisa receber CI integral no head final, ser incorporado e receber CI pós-merge antes de qualquer novo gate.
F4.6+ não foi iniciada; F3.7 permanece depois da F4.7. Tag remota e exclusão de refs continuam não
autorizadas.

## 6. Bloqueios atuais

Não resta blocker técnico local conhecido na F4.5. O PR administrativo #43 está aberto; o run inicial
`31459427729` começou no head `b304164`, mas este registro produzirá um head posterior e exigirá nova
CI integral. Até checks do head final, merge e CI pós-merge em `main`, F4.6+/F3.7 continuam
bloqueadas. Merge administrativo, tag remota e exclusão de refs continuam sem autorização.

## 7. Próxima ação exata

```text
PUBLICAR SOMENTE ESTE REGISTRO DOCUMENTAL NO PR #43 E AGUARDAR TODOS OS CHECKS DO HEAD FINAL,
INCLUINDO `CI REQUIRED`. NÃO MESCLAR, PUBLICAR TAG, EXCLUIR REF OU INICIAR F4.6+/F3.7.
DEPOIS DOS CHECKS VERDES, AGUARDAR AUTORIZAÇÃO NOMINAL NOVA PARA O MERGE ADMINISTRATIVO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/completed/F4.5.md` integralmente.
2. Leia DEC-015, as seções 1.1–1.2 e a Fase 4 do plano.
3. Confirme `.git`, branch/upstream, PR #43, head inicial `b304164`, run inicial `31459427729`,
   PR #42/head `9e8dfe8`, merge `4ae0de7` e runs `31457935429`/`31458482033`.
4. Execute somente a próxima ação exata. Divergência de escopo exige parar e recongelar.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- PR, CI, merge ou SHA só são registrados depois de observados;
- após promoção, arquivar o dossiê e preparar a reconciliação administrativa sem iniciar o gate seguinte.

---

*Atualizado em: 2026-08-11T01:45:06-03:00 | Fonte: plano principal + DEC-014 + DEC-015 + PRs #42/#43 observados*
