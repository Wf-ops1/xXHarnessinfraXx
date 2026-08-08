# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. [Dossiê ativo](docs/tasks/active/F3.5.md): problema, evidência, escopo, aceite e rollback.
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
- paths e efeitos confinados; comandos por `argv` e `shell=False`;
- secrets redigidos antes de persistência; estado necessário para retomar deve ser durável;
- histórico concluído fica nos dossiês e no Git, não é duplicado neste painel.

## 3. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2 — F2.1–F2.6 implementadas e promovidas |
| **Fase ativa** | Fase 3 — paths, ferramentas e workspace reais |
| **Tarefa ativa** | `F3.5` — terminal seguro por `argv` |
| **Gate** | `READY`; `ACTIVE / IMPLEMENTATION_AUTHORIZED` |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f3.5-safe-terminal`, criada de `6757fbf3b0a72a07080a7a7b45e5ae34f9bc3b86` |
| **Última main comprovada** | `6757fbf3b0a72a07080a7a7b45e5ae34f9bc3b86`; run `31279967619`, 11/11 verde |
| **Python** | runtime do workspace — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32; nenhuma dependência nova autorizada |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa anterior | `F3.6`, agora `PROMOTED` e arquivada neste primeiro commit do gate F3.5 |
| PR | #26; head final `919c28f3bf9ddd6f03d227784dd36808ba72a587`; merge `6757fbf3b0a72a07080a7a7b45e5ae34f9bc3b86` |
| CI do PR | run `31274543029`, evento `pull_request`, 11/11 jobs verdes incluindo `CI required` |
| CI pós-merge | run `31279967619`, evento `push` em `main`, SHA exato do merge, 11/11 jobs verdes |
| Linha comprovada | `main == origin/main == 6757fbf3b0a72a07080a7a7b45e5ae34f9bc3b86` antes desta branch |

## 5. Tarefa ativa

Leia integralmente: [F3.5](docs/tasks/active/F3.5.md), a
[DEC-013](docs/decisions/DEC-013-fase3-ordem-operacional.md) e o plano da Fase 3.

F3.5 exige nova autorização explícita; a promoção F3.6 foi certificada e a autorização nominal para
iniciar F3.5 foi observada em `2026-08-08T18:47:32-03:00`. Ela autoriza congelamento, checkpoint e
implementação local da F3.5, mas não autoriza push, abertura de PR, merge ou início de F3.8.

| Campo | Valor |
|---|---|
| **Objetivo** | substituir execução por shell string por contrato tipado, confinado, limitado e redigido |
| **Escopo** | terminal adapter, consumidor determinístico de verificação, documentação e testes F3.5 |
| **Proibido** | registrar tool operacional, tool loop/runtime/lifecycle, GitAdapter, edição, promoção, dependências, schemas e CI |
| **Checkpoint** | criar `checkpoint/f3.5-ready` no primeiro commit documental antes do código |
| **Estado remoto** | não existe branch remota ou PR F3.5; publicação permanece sem autorização |

## 6. Bloqueios atuais

Não há bloqueio para a implementação local estritamente congelada. F3.7, F3.8, registro do terminal
no tool loop, push, PR e merge continuam bloqueados por escopo e/ou autorização separada.

## 7. Próxima ação exata

```text
1. Criar o primeiro commit documental e a tag local checkpoint/f3.5-ready.
2. Implementar somente o contrato e os arquivos congelados no dossiê F3.5.
3. Executar todo o aceite congelado, registrar evidência e fechar localmente.
4. Pausar em COMPLETED_LOCAL / PROMOTION_PENDING.
5. Não fazer push, abrir PR, publicar tag, fazer merge ou iniciar F3.8 sem autorização própria.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia o dossiê ativo indicado na seção 5.
3. Leia a fase relevante no plano principal e DEC-013.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e checkpoint.
5. Execute somente a próxima ação exata; se escopo/estado divergir, pare e recongele o dossiê.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-08 | Fonte normativa: plano principal + DEC-012 + DEC-013*
