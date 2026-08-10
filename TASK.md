# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é o gate [F4.3](docs/tasks/active/F4.3.md); a última promoção certificada
   continua sendo a [F4.2](docs/tasks/completed/F4.2.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.2 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | `F4.3` — suficiência de contexto baseada em evidência; recongelamento R3 autorizado |
| **Gate** | F4.3 `READY` R3 / lifecycle `ACTIVE`; checkpoint local `checkpoint/f4.3-r3-ready` deve anteceder produção |
| **Última promoção** | F4.2 `PROMOTED`; reconciliação administrativa encerrada pelo PR #35 |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.3-evidence-context-sufficiency`, local e exclusiva, criada diretamente de `3705693` |
| **Baseline promovido** | `main == origin/main == 3705693`; run `31346860397`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.2` — indexador Python AST local e vinculado ao commit, promovida e arquivada |
| PR de implementação | #34; head final `2268f3fa276b017ad5b64efdb54e7abbf1f917d9`; 11/11 no run `31344668587` |
| Promoção da implementação | merge `212a9bfba2189ce8ca84d8eca76ede2d872b7d2c`; run `31345231098`, 11/11 |
| Reconciliação administrativa | PR #35; head final `fffd226a0d5567daa2ef399f054c20704f2315ca`; merge `370569377a1b065db479c239edde4016e1de5c0a`; run pós-merge `31346860397`, 11/11 |
| Fronteira | branches remotas preservadas; nenhuma tag remota ou exclusão de ref; F4.3 aberta somente para preparar seu gate; F3.7 não iniciada |

## 5. Tarefa ativa

O [dossiê F4.3](docs/tasks/active/F4.3.md) preserva o checkpoint R1 e a auditoria que reabriu o gate:
score vazio `0.85`, evaluator parcial `1.0`, snapshot vazio aceito, gates `0/0` e CLI reprovada com exit
zero. A [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) corrige o blocker de ownership:
o lifecycle prepara contexto antes do grafo e persiste a transição bloqueante; F4.4–F4.8 possuem owners
explícitos e não podem terminar como componentes desconectados.

Nenhum arquivo de produção foi alterado antes do R3. O gate congela quatro manifestos, identidade exata de artefato,
seis fórmulas Decimal, policy compilada, envelope imutável, start/resume e taxonomy de estado. Planner,
gates/verificação, repair, F3.7, MCP e memória semântica continuam fora da implementação F4.3.
F3.7 permanece depois da F4.7.

O R3 amplia exclusivamente a allowlist para a transição
`BLOCKED_INSUFFICIENT_CONTEXT → FAILED_RETRY_EXHAUSTED` e seu teste. Os checkpoints R1/R2 são
preservados, incluindo `checkpoint/f4.3-r2-ready`, e a autorização nominal inclui criar
`checkpoint/f4.3-r3-ready` e prosseguir com a
implementação depois dele.

## 6. Bloqueios atuais

Não há blocker aberto no contrato R3. O gate deve ser materializado pela tag local
`checkpoint/f4.3-r3-ready`; nenhuma implementação pode antecedê-lo. Os falsos sucessos de verificação
continuam conhecidos e reservados para F4.5–F4.8, sem autorização para corrigi-los agora. Publicação,
PR, merge e exclusão de refs permanecem não autorizados.

## 7. Próxima ação exata

```text
MATERIALIZAR `checkpoint/f4.3-r3-ready` ANTES DA PRIMEIRA EDIÇÃO DE PRODUÇÃO E IMPLEMENTAR SOMENTE O
ESCOPO R3 AUTORIZADO DA F4.3. NÃO CORRIGIR F4.4–F4.8, PUBLICAR BRANCH/TAG, ABRIR/MESCLAR PR,
EXCLUIR REFS OU INICIAR F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.3.md`, DEC-015, `docs/tasks/completed/F4.2.md` e DEC-014 integralmente.
3. Confirme o gate F4.3 `READY` R3, a branch exclusiva e os três checkpoints locais do dossiê.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e o baseline promovido da `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T01:15:18-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
