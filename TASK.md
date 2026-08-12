# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.1](docs/tasks/active/F5.1.md): dossiê ativo, escopo congelado, aceite e rollback.
3. [F3.7](docs/tasks/completed/F3.7.md) e [F4.8](docs/tasks/completed/F4.8.md): últimas entregas promovidas.
4. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
5. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.1 — resolver configuração no início da execução |
| **Gate** | `READY / ACTIVE`; implementação autorizada e ainda não iniciada |
| **Executor ativo** | `Codex`, único escritor; autorização nominal registrada em `2026-08-12T14:35:03-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.1-resolve-config`, local e sem upstream |
| **Baseline** | `main == origin/main == 846c59e78e6db9c9417ff1d8a69c560d2d08356e` antes da branch |
| **Fechamento administrativo anterior** | PR #52 mesclado em `846c59e`; não gera reconciliação recursiva |
| **CI do baseline** | run [31616226652](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31616226652), `workflow_dispatch`, success no SHA exato `846c59e` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13; `uv`, `python` e `py` indisponíveis no PATH |
| **Checkpoint READY** | tag local `checkpoint/f5.1-ready`, a materializar no commit documental antes do produto |

O evento do run `31616226652` é registrado como `workflow_dispatch`; não é apresentado como CI de
`push`. A PR administrativa #52 está fechada/mesclada e a referência remota `main` aponta para o mesmo
SHA validado pelo workflow. Nenhuma evidência negativa posterior foi observada.

## 3. Problema e fronteira da F5.1

O `ConfigResolver` atual mantém defaults hard-coded, aceita campos não tipados fora da rota de modelos
e o CLI não transporta perfil/overrides de configuração. A F5.1 deve resolver e validar as seis
camadas antes de criar estado, persistir somente a projeção redigida com digest e retomar
exclusivamente pelo bundle imutável.

O escopo está limitado a configuração, resource empacotado, composição CLI/runtime, persistência já
existente do bundle, testes e documentação associada. F5.2+, dependências, CI, schemas, providers,
tools, worktree e promoção estão fora da autorização.

## 4. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A implementação só começa depois do commit documental e da tag
local `checkpoint/f5.1-ready`.

Push, abertura ou merge de PR, tag remota, exclusão de refs, force-push, bypass e início de F5.2 não
estão autorizados.

## 5. Próxima ação exata

```text
MATERIALIZAR O CHECKPOINT READY DOCUMENTAL DA F5.1.
DEPOIS IMPLEMENTAR SOMENTE A ALLOWLIST E EXECUTAR O ACEITE CONGELADO.
NÃO PUBLICAR BRANCH, ABRIR PR, MESCLAR OU INICIAR F5.2.
```

## 6. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.1.md`, seções 1.1–1.2 e F5.1 do plano.
2. Confirme branch `task/f5.1-resolve-config`, baseline `846c59e`, checkpoint READY e workspace limpo
   ou contendo somente mudanças F5.1 registradas.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist do dossiê.
4. Execute somente a próxima ação exata; nenhum efeito remoto está autorizado.

---

*Atualizado em: 2026-08-12T14:35:03-03:00 | Fonte: F5.1 + PR #52 + run 31616226652 + baseline 846c59e*
