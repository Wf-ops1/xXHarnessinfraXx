# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F4.6 ativa](docs/tasks/active/F4.6.md): problema, evidências, escopo, aceite e rollback congelados.
3. [Plano principal](docs/plano_implementacao_harness_operacional.md): requisitos e dependências.
4. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md): reconciliação e ownership.
5. [Regras dos agentes](.agents/AGENTS.md) e [índice histórico](docs/tasks/README.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.5 e corretivas F3.C1/F3.C2/F4.C1 promovidas |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.6 — detectar stack e resolver comandos efetivos no worktree |
| **Gate** | `READY / ACTIVE`; checkpoints locais `checkpoint/f4.6-ready` e `checkpoint/f4.6-r1-ready` |
| **Executor ativo** | `Codex`, único escritor; autorização nominal em `2026-08-11T02:00:32-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.6-detect-stack-commands`, local, sem upstream |
| **Baseline promovido** | `main == origin/main == 46b70709b773a6bca0aa7adfd76d40b3cdf27e23` |
| **CI do baseline** | run `31459891130`, evento `push`, 11/11 verde, inclusive `CI required` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

A F4.5 foi incorporada pelo PR #42 no merge `4ae0de798607cf4fec13c0469fddb93d8024ead5`,
com CI pós-merge `31458482033` 11/11. Sua reconciliação administrativa PR #43 foi incorporada no
merge `46b70709b773a6bca0aa7adfd76d40b3cdf27e23`; a execução de `push` `31459891130` terminou
11/11 verde. As branches foram preservadas; nenhuma tag remota foi publicada nem ref excluída.
O histórico `POST_PROMOTION_BLOCKED` da F4.1 permanece encerrado pela corretiva F4.C1.

## 5. Tarefa ativa

O baseline reproduzido devolve stack ambígua sem interpretar `pyproject.toml`, escolhe comandos por
mapa estático/linguagem informada pelo chamador e converte ferramenta ausente em gate apenas reprovado.
A F4.6 deve produzir resolução imutável por configuração real e `argv`, executar exclusivamente no
`ProvisionedWorktree` e emitir `ERROR_PREREQUISITE` antes de qualquer gate quando configuração ou
ferramenta obrigatória faltar.

Persistência de resultado, status/tempo/exit/output/digest, guard de `COMPLETED`, correção decisória da
CLI e integração ao lifecycle pertencem à F4.7. Repair/retry pertence à F4.8; F3.7 permanece depois da
F4.7. Essas fronteiras não podem ser antecipadas.

## 6. Baseline, bloqueios e aceite inicial

- `.git` e runtime confirmados; branch criada diretamente do `main` promovido e workspace limpo;
- 31 testes focados de detector, F4.5, planner e planning lifecycle passaram;
- problema reproduzido por import/execução read-only e registrado integralmente no dossiê;
- allowlist, critérios positivos/negativos, rollback e auditoria de escopo congelados antes de produto.
- a primeira regressão obteve 733 passes e duas interferências ambientais; R1 preserva toda a suíte
  com `basetemp` e `LOCALAPPDATA` exclusivos fora do repositório.

Não há blocker técnico conhecido para implementar o escopo congelado. Push, abertura/merge de PR,
tag remota, exclusão de ref, force-push, bypass, F4.7, F4.8 e F3.7 não estão autorizados. Evidência
negativa nova reabre o gate e bloqueia promoção até correção e recertificação integral.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
CRIAR O CHECKPOINT LOCAL checkpoint/f4.6-r1-ready; REPETIR A REGRESSÃO INTEGRAL EM AMBIENTE
TEMPORÁRIO ISOLADO E, SE VERDE, EXECUTAR O RESTANTE DO ACEITE. NÃO PUBLICAR BRANCH/TAG, ABRIR OU
MESCLAR PR, EXCLUIR REF, ALTERAR PROTEÇÃO OU INICIAR F4.7/F4.8/F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.6.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e a DEC-015.
3. Confirme branch, status, checkpoint, baseline `46b70709`, run `31459891130` e runtime registrado.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T02:00:32-03:00 | Fonte: plano + DEC-015 + PR #43/run pós-merge observados*
