# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado pertence aos dossiês e ao Git.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, gate, bloqueios e próxima ação.
2. [F5.2](docs/tasks/active/F5.2.md): contrato congelado e evidência corrente.
3. [F5.1](docs/tasks/completed/F5.1.md): produto e promoção anteriores.
4. [F4.8](docs/tasks/completed/F4.8.md) e
   [F3.7 — promoção Git segura](docs/tasks/completed/F3.7.md): entregas anteriores; a F3.7 recebeu
   CI pós-merge `31568908128`.
5. [Plano principal](docs/plano_implementacao_harness_operacional.md): seções 1.1–1.2 e Fase 5.
6. [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md),
   [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md) e
   [regras dos agentes](.agents/AGENTS.md).

## 2. Estado atual

| Campo | Estado observado |
|---|---|
| **Fases concluídas** | Fases 0–4 no escopo planejado |
| **Fase ativa** | Fase 5 — governança e segurança no caminho crítico |
| **Tarefa ativa** | F5.2 — política unificada de autorização de tools |
| **Gate** | `COMPLETED_LOCAL / BRANCH_PUBLISHED / PR_PENDING` |
| **Executor ativo** | `Codex`, único escritor; autorizado nominalmente em `2026-08-12T17:34:35-03:00` |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f5.2-unified-policy` rastreando `origin/task/f5.2-unified-policy` |
| **Baseline** | `main == origin/main == fe95a91648a79c404565583c87c1cf357e8ab3a2` antes da branch |
| **Produto F5.2** | `ac665b945a2cfbadaa7672855219e624d7eca45e` |
| **Checkpoints F5.2** | `checkpoint/f5.2-ready`; `checkpoint/f5.2-complete` no commit documental final, ambos locais |
| **Certificação local** | `811 passed, 5 skipped, 6 subtests passed`; mypy, Ruff, compileall, build limpo e smoke da wheel verdes |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |

## 3. Última promoção comprovada

| Evidência | Resultado observado |
|---|---|
| Tarefa | F5.1 — resolver configuração no início da execução |
| Produto | commit `f246feb`; certificação local `792 passed, 5 skipped, 6 subtests passed` |
| PR de produto | [#53](https://github.com/Wf-ops1/Harnessinfra/pull/53), head final `f42af27`, CI `31629604755`, 11/11 success |
| Merge de produto | `c46910e50ede1196c9beb1242cb7bd708905d666`; CI de `push` pós-merge `31630446370`, 11/11 success |
| Reconciliação | PR administrativo [#54](https://github.com/Wf-ops1/Harnessinfra/pull/54), merge `fe95a91` |
| CI final | run `31633748837`, evento `push`, 11/11 success no SHA exato `fe95a91` |
| Fronteira | `checkpoint/f5.1-ready` e `checkpoint/f5.1-complete` somente locais; branches remotas preservadas; nenhuma tag/ref remota removida |

Nova evidência negativa prevalece sobre sucesso anterior e exige correção sem relaxamento,
recertificação integral e reconciliação antes de restaurar estado positivo.

## 4. Coordenação

Existe um único executor/escritor: `Codex`. A implementação respeitou a allowlist de policy,
router/tool loop, persistência da decisão, testes e documentação do dossiê. Nenhuma alteração
adicional de produto está autorizada. F5.3–F5.6, dependências, lockfile, CI, schemas/defaults de
policy e composição automática do lifecycle permanecem fora do escopo.

## 5. Tarefa ativa

A [F5.2](docs/tasks/active/F5.2.md) está `COMPLETED_LOCAL / PROMOTION_PENDING`. O produto unifica a
policy em um engine tipado default-deny, avalia os oito eixos exigidos, pré-autoriza o lote e persiste
a regra antes do efeito com digest no outcome. Novas gravações exigem decisão; replay histórico
permanece compatível. A wheel limpa e seu smoke confirmam que os módulos duplicados foram removidos.

## 6. Bloqueios e fronteiras externas

Não há bloqueio técnico conhecido. A branch foi publicada e o upstream configurado; os checkpoints
continuam locais. Abertura de PR, merge, tags remotas, remoção de branch/ref, force-push, bypass e
início da F5.3 não estão autorizados. O trust mode é somente uma dimensão da decisão nesta tarefa;
as restrições operacionais abrangentes continuam pertencendo à F5.3.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL PARA PUBLICAR O REGISTRO ADMINISTRATIVO E ABRIR O PR F5.2.
O WORKFLOW CI PARA task/** COMEÇA NO EVENTO pull_request CONTRA main, NÃO NO push DA BRANCH.
NÃO ABRIR PR, MESCLAR, CRIAR TAG REMOTA, REMOVER REFS OU INICIAR F5.3.
```

## 8. Retomada após perda de contexto

1. Leia `.agents/AGENTS.md`, este painel e `docs/tasks/active/F5.2.md` integralmente.
2. Confirme branch `task/f5.2-unified-policy`, checkpoints locais READY/COMPLETE, produto `ac665b9`
   e baseline `fe95a91`.
3. Use exclusivamente `.\.venv\Scripts\python.exe` e preserve a allowlist do dossiê.
4. Reproduza qualquer evidência negativa nova e não reduza critérios para obter verde.
5. Execute somente a próxima ação exata; efeitos remotos exigem autorização nominal nova.

---

*Atualizado em: 2026-08-12T18:25:54-03:00 | Fonte: F5.2/ac665b9/6f5d096 + publicação origin/task/f5.2-unified-policy + baseline fe95a91*
