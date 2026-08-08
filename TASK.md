# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. [Dossiê ativo](docs/tasks/active/F3.6.md): problema, evidência, escopo, aceite e rollback.
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
- sem mocks ou sucesso sintético em produção; integração indisponível falha explicitamente;
- paths e efeitos confinados; comandos futuros por `argv` e `shell=False`;
- secrets redigidos antes de persistência; estado necessário para retomar deve ser durável;
- histórico concluído fica nos dossiês e no Git, não é duplicado neste painel.

## 3. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2 — F2.1–F2.6 implementadas e promovidas |
| **Fase ativa** | Fase 3 — paths, ferramentas e workspace reais |
| **Tarefa ativa** | `F3.6` — worktree Git externo real e raiz autorizada |
| **Gate** | `READY`; `COMPLETED_LOCAL / PROMOTION_PENDING` |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f3.6-git-worktree`, criada de `8fac2d061e3b1a88d2683fab41af73a202091843` |
| **Última main comprovada** | `8fac2d061e3b1a88d2683fab41af73a202091843`; run `31272502445`, 11/11 verde |
| **Python** | `C:\Users\walla\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32; nenhuma dependência nova autorizada |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa anterior | `F3.4`, agora `PROMOTED` e arquivada neste primeiro commit do gate F3.6 |
| PR | #25; head `4d95d1a56513cf0ce8d027a0c250bd2bb4a8ae97`; merge `8fac2d061e3b1a88d2683fab41af73a202091843` |
| CI do PR | run `31271445092`, evento `pull_request`, 11/11 jobs verdes incluindo `CI required` |
| CI pós-merge | run `31272502445`, evento `push` em `main`, SHA exato do merge, 11/11 jobs verdes |
| Linha comprovada | `main == origin/main == 8fac2d061e3b1a88d2683fab41af73a202091843` antes desta branch |

## 5. Tarefa ativa

Leia integralmente: [F3.6](docs/tasks/active/F3.6.md), a
[DEC-013](docs/decisions/DEC-013-fase3-ordem-operacional.md) e o plano da Fase 3.

F3.6 exige nova autorização explícita; a pausa após F3.4 foi cumprida e a autorização nominal para
iniciar F3.6 foi observada em `2026-08-08T15:48:28-03:00`. A autorização separada para publicar a
branch e abrir o PR único também foi observada; ela não inclui merge nem efeitos F3.5/F3.7/F3.8.

| Campo | Valor |
|---|---|
| **Objetivo** | criar worktree Git externo real por execução, validar SHA/branch/raiz e fornecer `PathGuard` canônico |
| **Escopo** | `workspace/git_worktree.py`, exports, documentação e testes reais em repositórios temporários |
| **Proibido** | terminal, adapters/registrations, edição, commit candidato, promoção, cherry-pick, runtime/CLI, dependências, schemas e CI |
| **Estado local** | commits `2771f93`, `3816ece`, `122bbba`, `9432f29` e `5f6c234`; todos os gates verdes; esta reconciliação apenas registra fatos remotos observados |
| **Estado remoto** | branch publicada; PR #26 aberto para `main`; head inicial `5f6c234c8b11bfa6c6aed3ca53ab6ecabded34d9`; run inicial `31274365301`, 11/11 verde e sem conflitos |

## 6. Bloqueios atuais

Não há implementação ativa. A F3.6 concluiu todos os critérios locais, foi publicada somente após
autorização e permanece no PR #26. F3.5, F3.7, F3.8, integração com o tool loop e merge continuam
bloqueados; esta publicação não concede autorização de merge.

## 7. Próxima ação exata

```text
PAUSAR EM `COMPLETED_LOCAL / PROMOTION_PENDING`:
1. Publicar esta reconciliação no mesmo PR #26, sem nova branch, tag, PR ou ampliação de escopo.
2. Observar todos os 11 checks do novo head; check pendente, ausente ou falho bloqueia merge.
3. Mesmo com o head final verde e sem conflitos, não executar merge sem autorização explícita própria.
4. Após eventual merge autorizado, validar a CI `push` no SHA exato de `main` e pausar novamente.
5. Não iniciar F3.5 sem promoção completa da F3.6 e nova autorização explícita nominal.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia o dossiê ativo indicado na seção 5, quando houver.
3. Leia a fase relevante no plano principal.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e upstream.
5. Confirme no GitHub o último merge e a CI pós-merge do SHA registrado.
6. Execute somente a próxima ação exata; se escopo/estado divergir, pare e recongele o dossiê.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- não copiar dossiê concluído, logs extensos, contratos completos ou histórico de fases para o painel;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- entre tarefas, `active/` pode conter somente seu README e o painel deve apontar `nenhuma tarefa ativa`;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-08 | Fonte normativa: plano principal + DEC-012*
