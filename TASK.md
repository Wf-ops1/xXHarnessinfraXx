# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não existe dossiê de implementação ativo. A corretiva
   [F4.C1](docs/tasks/completed/F4.C1.md) foi promovida e está em reconciliação administrativa local;
   a última tarefa anterior permanece a [F4.4](docs/tasks/completed/F4.4.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.4 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | nenhuma tarefa ativa de implementação; reconciliação administrativa F4.C1 local; F4.5 não iniciada |
| **Gate** | F4.C1 `PROMOTED`; `docs/promote-f4.c1` em `LOCAL_READY / PUBLICATION_PENDING` |
| **Última promoção** | F4.C1 `PROMOTED`; PR #40 incorporado e CI pós-merge verde no SHA exato |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.c1`, local e sem upstream, criada de `main == origin/main == 3905d02` |
| **Baseline promovido** | `main == origin/main == 3905d02`; run `31453662008`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | path versionado anterior indisponível neste checkout; nenhum runtime será trocado silenciosamente |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.C1` — imutabilidade concorrente da publicação de snapshots, promovida e arquivada localmente |
| PR de implementação | PR #40; head final `65c54338b5753d31c0b0ed15ab6cf9ba1486f493`; 11/11 no run `31453116947` |
| Promoção da implementação | merge `3905d02d575fc177d917f605b7e1a9b6a658c818`; run `31453662008`, 11/11 |
| Reconciliação administrativa | branch local `docs/promote-f4.c1`; validação concluída, publicação pendente |
| Fronteira | branch remota de implementação preservada; nenhuma tag publicada ou ref excluída; F4.5/F3.7 não iniciadas |

## 5. Tarefa ativa

Não existe implementação ativa. A F4.4 `PROMOTED` permanece como a última tarefa funcional anterior.
A corretiva [F4.C1](docs/tasks/completed/F4.C1.md) substituiu o
overwrite concorrente por claim atômico exclusivo com `os.link`, foi recertificada localmente em
`702 passed, 2 skipped, 6 subtests passed` e promovida pelo PR #40. O head final `65c5433` recebeu
11/11 checks no run `31453116947`; o merge `3905d02` recebeu 11/11 na CI de `push` `31453662008`.

O estado anterior `POST_PROMOTION_BLOCKED` foi encerrado pela correção e recertificação no SHA
promovido. A pausa corrente é exclusivamente administrativa: a branch `docs/promote-f4.c1` precisa
ser validada, publicada, incorporada e receber CI pós-merge verde antes de qualquer novo gate. F4.5 e
F4.6–F4.8 continuam fora do escopo; F3.7 permanece depois da F4.7. Nenhuma delas, nem MCP ou memória
semântica, foi iniciada.

## 6. Bloqueios atuais

Não resta blocker técnico local conhecido dentro do escopo F4.C1. A implementação já foi incorporada e a CI
pós-merge está verde; resta concluir a reconciliação administrativa obrigatória. Até seu PR, merge e
CI pós-merge em `main`, F4.5/F3.7 continuam bloqueadas. Publicação/abertura do PR administrativo,
merge administrativo, publicação remota de tag e exclusão de refs continuam sem autorização.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL NOVA PARA PUBLICAR `docs/promote-f4.c1` E ABRIR O PR ADMINISTRATIVO.
NÃO PUBLICAR, ABRIR/MESCLAR PR, PUBLICAR TAG REMOTA, EXCLUIR REFS OU INICIAR F4.5/F3.7 SEM ESSA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/completed/F4.C1.md`, `docs/tasks/completed/F4.1.md`, DEC-015, DEC-014, as seções
   1.1–1.2 e a Fase 4 do plano integralmente.
3. Confirme F4.1–F4.4 historicamente `PROMOTED`, PR #40/head `65c5433`, merge `3905d02`, runs
   `31453116947`/`31453662008` e a recertificação append-only registrada no dossiê concluído.
4. Confirme `.git`, branch `docs/promote-f4.c1`, ausência de upstream, `git status --short --branch`,
   `git log -10` e o baseline `main == origin/main == 3905d02`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-11T00:03:56-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
