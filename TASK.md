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
| **Gate** | `PR_OPEN / CHECKS_PENDING`; aceite integral local verde |
| **Executor ativo** | `Codex`, único escritor; autorização nominal registrada em `2026-08-12T14:35:03-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.1-resolve-config`, publicada e rastreando `origin/task/f5.1-resolve-config` |
| **Baseline** | `main == origin/main == 846c59e78e6db9c9417ff1d8a69c560d2d08356e` antes da branch |
| **Fechamento administrativo anterior** | PR #52 mesclado em `846c59e`; não gera reconciliação recursiva |
| **CI do baseline** | run [31616226652](https://github.com/Wf-ops1/Harnessinfra/actions/runs/31616226652), `workflow_dispatch`, success no SHA exato `846c59e` |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13; `uv`, `python` e `py` indisponíveis no PATH |
| **Checkpoint READY** | `checkpoint/f5.1-ready` → `930cabd2b22672048357df2b91385c74af1b248f` |
| **Checkpoint COMPLETE** | `checkpoint/f5.1-complete` → `f246feb2a70bb83f08ff31341525fd29bd6d10f8` |
| **Produto F5.1** | `f246feb2a70bb83f08ff31341525fd29bd6d10f8` |
| **PR F5.1** | [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), aberto e não draft; base `846c59e`, head inicial `436afa1` |
| **Aceite local** | `792 passed, 5 skipped, 6 subtests passed`; Ruff, mypy, compileall, build e smoke da wheel verdes |

O evento do run `31616226652` é registrado como `workflow_dispatch`; não é apresentado como CI de
`push`. A PR administrativa #52 está fechada/mesclada e a referência remota `main` aponta para o mesmo
SHA validado pelo workflow. Nenhuma evidência negativa posterior foi observada.

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F3.7 — promoção Git segura |
| Produto | PR #51, merge `10d75408`, CI pós-merge `31568908128` |
| Reconciliação | PR administrativo #52 incorporado em `846c59e` |
| Baseline seguinte | workflow `CI` `31616226652`, success no SHA exato `846c59e` |
| Fronteira | checkpoints anteriores somente locais; nenhuma tag/ref remota removida |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. O workspace não possuía mudanças preexistentes antes da
branch F5.1; todo o diff corrente deve permanecer dentro da allowlist do dossiê ativo.

## 5. Tarefa ativa

O `ConfigResolver` agora lê defaults do pacote instalado, resolve as seis camadas, valida a
configuração inteira por Pydantic e entrega ao lifecycle somente uma projeção redigida. CLI e runtime
usam o mesmo resolvedor; `resume` valida a projeção e o digest do bundle sem reler arquivos vivos.

O escopo está limitado a configuração, resource empacotado, composição CLI/runtime, persistência já
existente do bundle, testes e documentação associada. F5.2+, dependências, CI, schemas, providers,
tools, worktree e promoção estão fora da autorização.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A tarefa saiu de `COMPLETED_LOCAL / PROMOTION_PENDING` após a
autorização nominal `autorizo` registrada em `2026-08-12T15:44:22-03:00`: somente a branch foi
publicada e o PR #53 foi aberto. Os checkpoints permanecem exclusivamente locais.

Merge do PR, tag remota, exclusão de refs, force-push, bypass e início de F5.2 não estão autorizados.

## 7. Próxima ação exata

```text
OBSERVAR TODOS OS CHECKS DO HEAD FINAL DO PR #53 E REGISTRAR QUALQUER EVIDÊNCIA NEGATIVA.
NÃO MESCLAR, PUBLICAR TAGS OU INICIAR F5.2 SEM NOVA AUTORIZAÇÃO NOMINAL.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel, `docs/tasks/active/F5.1.md`, seções 1.1–1.2 e F5.1 do plano.
2. Confirme branch `task/f5.1-resolve-config`, baseline `846c59e`, checkpoint READY e workspace limpo
   ou contendo somente mudanças F5.1 registradas.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist do dossiê.
4. Execute somente a próxima ação exata; leitura dos checks está autorizada, mas merge e demais
   efeitos remotos exigem nova autorização nominal.

---

*Atualizado em: 2026-08-12T15:44:22-03:00 | Fonte: F5.1 + PR #53 + PR #52 + run 31616226652 + baseline 846c59e*
