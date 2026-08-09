# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê de implementação ativo; a última promoção certificada é a
   [F4.1](docs/tasks/completed/F4.1.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.2 não iniciada |
| **Gate** | F4.1 `PROMOTED`; PR administrativo #33 aberto com checks pendentes |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.1`, publicada e rastreando `origin/docs/promote-f4.1`; checkpoint local em `467aff6` |
| **Baseline promovido** | `main == origin/main == 12ce3b7`; run `31323952381`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.1` — armazenamento íntegro do índice estrutural, promovida e arquivada |
| PR de implementação | #32; head final `3ba0e254d9d7425113ffcbcd6d22b5c663d7255e`; 11/11 no run `31322494169` |
| Promoção da implementação | merge `12ce3b7360a6035fb354326261fc409de15e29ec`; run `31323952381`, 11/11 |
| Reconciliação administrativa | PR #33 aberto; head inicial `9a0733a`; run inicial `31328788064` em andamento |
| Fronteira | branch remota de implementação preservada; nenhuma tag remota ou exclusão de ref; F4.2 não iniciada |

## 5. Tarefa ativa

Não há nenhuma tarefa ativa. A F4.1 foi incorporada pelo PR #32 e certificada no
[dossiê concluído](docs/tasks/completed/F4.1.md): o head final passou 11/11 checks no run
`31322494169`, e o merge `12ce3b7` passou outros 11/11 no run pós-merge `31323952381`.

A reconciliação exigida pela DEC-014 foi publicada no PR administrativo #33 a partir da branch
`docs/promote-f4.1`; seus checks estão pendentes e nenhum resultado foi antecipado como sucesso.
O indexador Python real, rebuild e descoberta de símbolos permanecem na F4.2, que não foi iniciada.
F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico local conhecido. A pendência corrente é concluir todos os checks do head final
do PR #33, incluindo `CI required`. Merge exige autorização nominal própria; até merge e CI pós-merge
verdes no SHA exato de `main`, F4.2 e qualquer outra implementação permanecem pausadas.

## 7. Próxima ação exata

```text
AGUARDAR E REVALIDAR TODOS OS CHECKS DO HEAD FINAL DO PR #33, INCLUINDO `CI required`. Somente se
todos ficarem verdes, solicitar autorização nominal separada para o merge. Não iniciar F4.2, publicar
tags, excluir refs ou mesclar o PR sem autorização própria.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/completed/F4.1.md` integralmente.
3. Leia F4.1 no plano principal e, se houver promoção, DEC-014.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e CI da `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-09T15:21:08-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
