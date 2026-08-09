# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é [F4.1](docs/tasks/active/F4.1.md); a última promoção de implementação
   certificada permanece no [dossiê F3.8](docs/tasks/completed/F3.8.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.1 — concluída localmente; promoção pendente |
| **Gate** | F4.1 `READY`; lifecycle `COMPLETED_LOCAL / PROMOTION_PENDING`; PR #32 aberto com checks pendentes |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.1-index-storage`, publicada e rastreando `origin/task/f4.1-index-storage` |
| **Baseline promovido** | `main == origin/main == e4292ca`; run `31319202731`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F3.8` — edição real confinada e Serena MCP explícito, promovida pelo PR #29 e arquivada |
| PR de implementação | #29; head final `f941c89fd0ec112aca82621ab9e11244f05962aa`; 11/11 no run `31292195340` |
| Promoção da implementação | merge `e6b5b84bbe8299f8e04b9ad28c0ca0a86269c98f`; run `31295594376`, 11/11 |
| PR administrativo | #30; head final `bd0bda9385db850208f125e69757118ee9fe2b27`; 11/11 no run `31316549732` |
| Fechamento administrativo | merge `c2aa89b50ad32dc90b26b70087dbd795e32f0042`; run `31316853244`, 11/11 |
| Correção transversal | PR #31; merge `e4292ca52456708af7c2afe4e4471b1a721676a6`; run `31319202731`, 11/11 |
| Fronteira | branch remota anterior preservada; nenhuma tag remota; F4.1 iniciada somente localmente |

## 5. Tarefa ativa

A F4.1 foi implementada e validada localmente no commit
`b3686e0d8eaf6ae0b31cf29a2ecb75426d15da1b`, com contrato e evidências no
[dossiê ativo](docs/tasks/active/F4.1.md). Ela corrige o path divergente entre escritor/consumidor,
proíbe `HEAD` persistido, define schema único de símbolos e exige status/digest válidos antes de
servir snapshots. O indexador Python real, rebuild e descoberta de símbolos permanecem na F4.2.

O baseline inclui o fechamento pelo PR administrativo #30 e a correção transversal já incorporada
pelo PR #31 no merge `e4292ca`, cuja CI de `push` concluiu 11/11 verde no SHA exato de `main`.
A branch F4.1 foi publicada e o PR #32 aberto; merge, tags e exclusão de refs não foram autorizados.
F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico local conhecido: aceite, regressão, quality, build, smoke e escopo estão verdes.
A ausência de snapshot real permanece comportamento esperado até F4.2 e agora falha explicitamente.
O bloqueio corrente é o CI pendente do PR #32. Merge exige todos os checks verdes e autorização nova;
F4.2 não pode iniciar antes de merge, CI pós-merge e reconciliação administrativa da F4.1.

## 7. Próxima ação exata

```text
AGUARDAR E REVALIDAR TODOS OS CHECKS DO HEAD FINAL DO PR #32, INCLUINDO `CI required`. Somente se
todos ficarem verdes, solicitar autorização nominal separada para o merge. F4.2, F3.7, merge, tags e
exclusão de refs não estão autorizados implicitamente; depois de eventual merge será obrigatória a
reconciliação `docs/promote-f4.1`.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.1.md` integralmente.
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

*Atualizado em: 2026-08-09T12:55:45-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
