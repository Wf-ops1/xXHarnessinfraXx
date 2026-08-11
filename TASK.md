# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [Dossiê ativo F4.6](docs/tasks/active/F4.6.md): contrato, implementação, reparos e aceite preservados.
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
| **Gate** | `LOCAL_READY / PR_UPDATE_PENDING`; R3 recertificado localmente seleciona por `sys.prefix` e preserva seu path até o spawn; merge segue bloqueado até publicação autorizada e CI POSIX verde |
| **Executor ativo** | `Codex`, único escritor; autorização nominal em `2026-08-11T02:00:32-03:00`; continuidade R3 em `2026-08-11T11:28:28-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.6-detect-stack-commands`, rastreando `origin/task/f4.6-detect-stack-commands`; reparo local `167dbe5`, upstream/PR ainda em `0d10d0a` |
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

O `VerificationEngine` agora exige `ProvisionedWorktree`, detecta a stack pela configuração real,
resolve a suíte inteira em contratos imutáveis de `argv`/cwd/executável/fonte e valida todos os
pré-requisitos antes do primeiro subprocesso. Configuração ausente, ambígua ou inválida, stack não
suportada e ferramenta/módulo indisponível produzem `VerificationPrerequisiteError` com código
`ERROR_PREREQUISITE`. O runner usa o `PathGuard` do worktree e o terminal tipado promovido.

O PR #44 foi aberto no head `f258541`, mas a CI `31463009231` reabriu o gate: os jobs Tests Ubuntu
3.11/3.14 executaram o Python base em vez do launcher `.venv/bin/python` e falharam com
`No module named pytest`. O R2 removeu a primeira dereferência, no resolver, e foi publicado em
`0d10d0a`; a CI `31463962634` reproduziu a mesma falha.

A inspeção completa provou uma segunda dereferência: o `TerminalAdapter` transformava o launcher
autorizado em seu alvo canônico antes do spawn. Os logs não discriminam se `uv run` também fornece
`sys.executable` base. O R3 `167dbe5` agora escolhe o launcher por `sys.prefix` quando há venv ativo,
preserva esse path através da policy do terminal e falha sem fallback se ele não estiver disponível
ou mudar de alvo antes do efeito.

Persistência de resultado, status/tempo/exit/output/digest, guard de `COMPLETED`, correção decisória da
CLI e integração ao lifecycle pertencem à F4.7. Repair/retry pertence à F4.8; F3.7 permanece depois da
F4.7. Essas fronteiras não podem ser antecipadas.

## 6. Evidência de conclusão local

- implementação: `507c216`; recongelamento ambiental: `a4081b2`; reparo R2: `f26c124`;
- aceite focado: 35 testes; worktree/terminal/guard: 51; compatibilidade F4: 109;
- regressão R1 integral e isolada: `735 passed, 2 skipped, 6 subtests passed`;
- recertificação integral R2: `736 passed, 3 skipped, 6 subtests passed`;
- recongelamento R3: `ce07850`, tag local `checkpoint/f4.6-r3-ready`; reparo R3: `167dbe5`;
- aceite R3: `38 passed, 1 skipped`; worktree/terminal/guard: `51 passed, 2 skipped`;
- regressão integral R3: `738 passed, 5 skipped, 6 subtests passed`; compatibilidade: `109 passed`;
- documentação, ledger e UTF-8 finais R2/R3: `25 passed, 6 subtests passed` em cada recertificação;
- mypy Windows/Linux: 106 arquivos, zero issues; Ruff, compileall e `git diff --check`: verdes;
- build isolado de sdist/wheel e smoke da wheel: verdes; `uv 0.12.3` foi instalado somente no venv
  temporário do smoke, sem instalação global ou mudança no projeto;
- escopo proibido permaneceu byte-idêntico e o workspace terminou limpo.

O R3 local fechou verde, mas o PR #44 ainda aponta para o head R2 `0d10d0a`. Merge, tag remota,
exclusão de ref, force-push, bypass, F4.7, F4.8 e F3.7 não estão autorizados; promoção depende de
publicação nominalmente autorizada e nova CI integral verde no head R3.

Checkpoints locais preservados: `checkpoint/f4.6-ready`, `checkpoint/f4.6-r1-ready`,
`checkpoint/f4.6-complete`, `checkpoint/f4.6-r2-ready` e `checkpoint/f4.6-r2-complete`.
`checkpoint/f4.6-r3-ready` está em `ce07850`; a conclusão local R3 recebe
`checkpoint/f4.6-r3-complete` nesta reconciliação documental final.

Evidência negativa sempre prevalece sobre sucesso anterior e exige recertificação integral.

## 7. Próxima ação exata

```text
FINALIZAR ESTA RECONCILIAÇÃO LOCAL E PRESERVAR O HEAD R3. AGUARDAR AUTORIZAÇÃO NOMINAL NOVA PARA
PUSH/ATUALIZAÇÃO DO PR #44; DEPOIS EXIGIR CI COMPLETA VERDE, INCLUSIVE UBUNTU 3.11/3.14, ANTES DE
QUALQUER MERGE. NÃO PUBLICAR TAG, MESCLAR PR, EXCLUIR REF, ALTERAR PROTEÇÃO OU INICIAR
F4.7/F4.8/F3.7 SEM AUTORIZAÇÃO NOMINAL NOVA.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo e `docs/tasks/active/F4.6.md` integralmente.
2. Leia as seções 1.1–1.2/Fase 4 do plano e a DEC-015.
3. Confirme branch, status, checkpoints, PR #44/runs `31463009231` e `31463962634`, baseline e runtime.
4. Execute somente a próxima ação exata; divergência de escopo exige parar e recongelar.

---

*Atualizado em: 2026-08-11T11:43:05-03:00 | Fonte: PR #44/runs negativos + recertificação local R3 F4.6*
