# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é o gate corretivo
   [F4.C1](docs/tasks/active/F4.C1.md); a última promoção histórica permanece a
   [F4.4](docs/tasks/completed/F4.4.md).
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
| **Tarefa ativa** | F4.C1 — imutabilidade concorrente da publicação de snapshots; F4.5 não iniciada |
| **Gate** | F4.C1 `READY / ACTIVE`; estado operacional `POST_PROMOTION_BLOCKED` |
| **Última promoção** | F4.4 `PROMOTED` historicamente; PR administrativo #39 incorporado e CI pós-merge verde |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.c1-snapshot-publication-concurrency`, criada de `main` limpa e sincronizada |
| **Baseline promovido** | `main == origin/main == 94641d2`; run `31447628152`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | path versionado anterior indisponível neste checkout; nenhum runtime será trocado silenciosamente |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.4` — plano tipado e específico, promovida e arquivada localmente |
| PR de implementação | PR #38; head final `fbdb6ee3d2e1728cbc691b98f04846989475c614`; 11/11 no run `31442203348` |
| Promoção da implementação | merge `93ce4ce9f4f0042c58d64103528b6c359a475bd9`; run `31445624269`, 11/11 |
| Reconciliação administrativa | PR #39; head final `bb759c5`; merge `94641d27384d370faf013825e7e9955c721cf420`; run pós-merge `31447628152`, 11/11 |
| Fronteira | branches remotas preservadas; nenhuma tag publicada ou exclusão de ref; F4.5/F3.7 não iniciadas |

## 5. Tarefa ativa

O gate [F4.C1](docs/tasks/active/F4.C1.md) corrige uma evidência negativa pós-promoção no contrato
F4.1: duas publicações concorrentes divergentes que observam o destino ausente podem concluir com
sucesso e a segunda sobrescreve o snapshot validado pela primeira. A correção está congelada para
claim exclusivo por SHA, idempotência concorrente, conflito divergente tipado e vencedor imutável.

F4.1–F4.4 permanecem historicamente `PROMOTED`, mas o estado corrente é `POST_PROMOTION_BLOCKED`.
F4.5 e F4.6–F4.8 continuam fora do escopo; F3.7 permanece depois da F4.7. Nenhuma delas, nem MCP ou
memória semântica, pode começar antes da correção, recertificação integral, promoção e reconciliação
administrativa da F4.C1.

## 6. Bloqueios atuais

O blocker técnico reproduzido está na publicação concorrente de
`src/ai_engineering_harness/indexer/snapshot_manager.py`: `first=success`, `second=success`,
`final=second`. Até a F4.C1 ser promovida e reconciliada, F4.5/F3.7 permanecem bloqueadas. Push, PR,
merge, publicação de tag e exclusão de refs continuam sem autorização.

## 7. Próxima ação exata

```text
IMPLEMENTAR SOMENTE A F4.C1 DEPOIS DO CHECKPOINT READY; PROVAR IDEMPOTÊNCIA/CONFLITO CONCORRENTES E
VENCEDOR IMUTÁVEL; REPETIR ACEITE F4.1–F4.4, REGRESSÃO, QUALITY E PACKAGE/SMOKE. NÃO PUBLICAR, ABRIR
PR, MESCLAR, EXCLUIR REFS OU INICIAR F4.5/F3.7 SEM AUTORIZAÇÃO NOMINAL NOVA.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.C1.md`, `docs/tasks/completed/F4.1.md`, DEC-015, DEC-014, as seções
   1.1–1.2 e a Fase 4 do plano integralmente.
3. Confirme F4.1–F4.4 historicamente `PROMOTED`, PR #39/merge `94641d2`, run `31447628152` e a
   evidência negativa concorrente registrada no dossiê ativo.
4. Confirme `.git`, branch `task/f4.c1-snapshot-publication-concurrency`, checkpoint READY, upstream,
   `git status --short --branch`, `git log -10` e o baseline de `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T23:11:37-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
