# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. Não existe nenhuma tarefa ativa de implementação. A
   [F4.6](docs/tasks/completed/F4.6.md) foi promovida e está em reconciliação administrativa local.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.6 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | nenhuma implementação ativa; PR administrativo F4.6 #45 aberto; F4.7/F4.8/F3.7 não iniciadas |
| **Gate** | F4.6 `PROMOTED`; PR #45 em `ADMIN_PR_OPEN / CHECKS_PENDING` |
| **Executor ativo** | `Codex`, único escritor; reconciliação e arquivamento autorizados nominalmente em `2026-08-11T13:16:05-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.6`, rastreando `origin/docs/promote-f4.6`; PR #45; head inicial `5882e42` |
| **Baseline promovido** | `main == origin/main == a4fd1dabe09c9f6064f7c34b0ddb6bc62761135d` |
| **CI do baseline** | run `31510277593`, evento `push`, 11/11 verde em `2m47s`, inclusive `CI required` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F4.6 — detectar stack e resolver comandos efetivos, promovida e arquivada localmente |
| PR de implementação | PR #44; head final `00e83574da789fa58f22f928b5290b9471264a63`; run `31505324814`, 11/11 |
| Promoção | merge `a4fd1dabe09c9f6064f7c34b0ddb6bc62761135d`; run `31510277593`, 11/11 |
| Reconciliação administrativa | PR #45 aberto no head inicial `5882e42`; run inicial `31512347572` em andamento |
| Fronteira | branch remota de implementação preservada; checkpoints somente locais; nenhuma tag publicada ou ref excluída |

O histórico `POST_PROMOTION_BLOCKED` da F4.1 permanece encerrado pela corretiva F4.C1. As evidências
negativas R2/R3 da F4.6 continuam no dossiê; perderam precedência operacional somente depois do R3,
da recertificação integral, da CI do head final e da CI pós-merge verdes.

## 5. Tarefa ativa

Não existe nenhuma tarefa ativa de implementação. A F4.6 exige `ProvisionedWorktree`, detecta a
stack pela configuração real, resolve toda a suíte em contratos imutáveis de `argv`/cwd/executável e
valida todos os pré-requisitos antes do primeiro subprocesso. Configuração, stack, ferramenta ou
módulo indisponível falham `ERROR_PREREQUISITE` antes de efeitos.

As CIs `31463009231` e `31463962634` falharam nos testes Ubuntu porque o launcher do venv era
dereferenciado até o Python base. O R2 `f26c124` foi insuficiente. O R3 `167dbe5` seleciona pelo
`sys.prefix`, preserva o path no `TerminalAdapter` até o spawn e falha fechado diante de retargeting.
O aceite local concluiu `738 passed, 5 skipped, 6 subtests passed`.

O head final `00e8357` recebeu 11/11 checks no run `31505324814`, inclusive Ubuntu 3.11/3.14. A
primeira tentativa deixou o check Windows 3.14 órfão apesar dos passos verdes; a repetição restrita
do job e do `CI required` encerrou a tentativa 2 integralmente verde. O merge `a4fd1da` recebeu 11/11
na CI de `push` `31510277593`. A reconciliação administrativa está aberta no PR #45; o run inicial
`31512347572` pertence ao head `5882e42`, anterior ao registro documental final desta observação.

Persistência de resultado, status/tempo/exit/output/digest, guard de `COMPLETED`, decisão de exit da
CLI e integração ao lifecycle pertencem à F4.7. Repair/retry pertence à F4.8; F3.7 permanece depois
da F4.7. Nenhuma dessas tarefas foi iniciada.

Checkpoints locais preservados: `checkpoint/f4.6-ready`, `checkpoint/f4.6-r1-ready`,
`checkpoint/f4.6-complete`, `checkpoint/f4.6-r2-ready`, `checkpoint/f4.6-r2-complete`,
`checkpoint/f4.6-r3-ready` e `checkpoint/f4.6-r3-complete`.

## 6. Bloqueios atuais

Não resta blocker técnico conhecido na F4.6. O PR administrativo #45 está aberto; o run inicial
`31512347572` começou no head `5882e42`, mas este registro produzirá um head posterior e exigirá nova
CI integral. Até checks do head final, merge e CI pós-merge em `main`, F4.7/F4.8/F3.7 continuam
bloqueadas. Tag remota e exclusão de refs permanecem fora do escopo autorizado.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
PUBLICAR SOMENTE ESTE REGISTRO DOCUMENTAL NO PR #45 E EXIGIR CI INTEGRAL NO HEAD FINAL, INCLUINDO
`CI REQUIRED`. DEPOIS DOS CHECKS VERDES, MESCLAR POR MERGE COMMIT DENTRO DA AUTORIZAÇÃO NOMINAL
ATUAL E VALIDAR A CI DE PUSH. NÃO PUBLICAR TAG, EXCLUIR REF OU INICIAR F4.7/F4.8/F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/completed/F4.6.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e as DEC-014/DEC-015.
3. Confirme branch/upstream, PR #45/head inicial `5882e42`, run inicial `31512347572`, PR #44/head
   `00e8357`, merge `a4fd1da`, runs `31505324814`/`31510277593` e ausência de tags remotas.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T13:26:18-03:00 | Fonte: plano + DEC-014/DEC-015 + PRs #44/#45 observados*
