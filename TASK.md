# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. [Dossiê ativo](docs/tasks/active/F3.4.md): problema, evidência, escopo, aceite e rollback.
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
| **Tarefa ativa** | `F3.4` — path guard confinado à raiz autorizada |
| **Gate** | `READY`; implementação local autorizada após checkpoint documental |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f3.4-path-guard`, criada de `d2502b091941089d1c70a67dc2f8e7c0973cf9c4` |
| **Última main comprovada** | `d2502b091941089d1c70a67dc2f8e7c0973cf9c4`; run `31266993044`, 11/11 verde |
| **Python** | `C:\Users\walla\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32; nenhuma dependência nova autorizada |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa anterior | `F3.C2`, agora `PROMOTED` e arquivada neste primeiro commit do gate F3.4 |
| PR | #24; head `bf38d31b391352308b0e2b53e586b0cf493a2471`; merge `d2502b091941089d1c70a67dc2f8e7c0973cf9c4` |
| CI do PR | run `31242510166`, evento `pull_request`, 11/11 jobs verdes incluindo `CI required` |
| CI pós-merge | run `31266993044`, evento `push` em `main`, SHA exato do merge, 11/11 jobs verdes |
| Linha comprovada | `main == origin/main == d2502b091941089d1c70a67dc2f8e7c0973cf9c4` antes desta branch |

## 5. Tarefa ativa

Leia integralmente: [F3.4](docs/tasks/active/F3.4.md), a
[DEC-013](docs/decisions/DEC-013-fase3-ordem-operacional.md) e o plano da Fase 3.

F3.4 exige nova autorização explícita; a pausa após F3.C2 foi cumprida e `continue`, respondido
diretamente ao próximo passo auditado, foi observado em `2026-08-08T14:45:06-03:00`. A autorização
não inclui push, PR, merge nem efeitos F3.5–F3.8.

| Campo | Valor |
|---|---|
| **Objetivo** | validar paths contra raiz explícita, bloquear traversal/escape/`.git`/tamanho e produzir path relativo para journal |
| **Escopo** | nova primitiva em `security/path_guard.py`, export público, documentação e testes focados |
| **Proibido** | adapters, registrations, terminal, worktree, subprocesso/Git, promoção e edição F3.5–F3.8; dependências, schemas e CI |
| **Estado local** | gate documental `READY`; nenhum arquivo de implementação alterado antes do checkpoint |
| **Estado remoto** | somente `main` promovida foi observada; branch F3.4 ainda não publicada e PR inexistente |

## 6. Bloqueios atuais

O realinhamento DEC-012 foi auditado sem achado blocker/high e encerrado neste gate. A implementação
F3.4 pode começar somente depois do primeiro commit documental/tag `checkpoint/f3.4-ready`. F3.5–F3.8
e qualquer habilitação de efeitos continuam bloqueados.

## 7. Próxima ação exata

```text
EXECUTAR SOMENTE F3.4 LOCAL:
1. Criar o primeiro commit documental e a tag `checkpoint/f3.4-ready`.
2. Implementar somente o path guard e testes do allowlist congelado.
3. Executar aceite focado, compatibilidade, documentação, regressão, quality, package e escopo.
4. Registrar `COMPLETED_LOCAL / PROMOTION_PENDING` e pausar antes de push/PR.
5. Push e PR único da F3.4 exigem autorização explícita própria depois dos gates locais verdes.
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
