# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê ativo. A última promoção certificada está no [dossiê F3.5](docs/tasks/completed/F3.5.md).
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
| **Tarefa ativa** | nenhuma tarefa ativa; F3.8 é apenas a próxima tarefa planejada |
| **Gate** | `PAUSED / NO_ACTIVE_GATE` |
| **Executor ativo** | nenhum executor de implementação; aguardando autorização nominal |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Baseline promovido** | F3.5 em `b6a4a24179271a8caa22252f71d08c35e13e7a41`; run `31285547886`, 11/11 verde |
| **Python** | runtime do workspace — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32; nenhuma dependência nova autorizada |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F3.5` — terminal seguro por `argv`, agora `PROMOTED` e arquivada |
| PR | #27; head final `e6d947a2713e61c0700154cb7453f8bc0a7c342f`; 11/11 no run `31284043501` |
| Merge | `b6a4a24179271a8caa22252f71d08c35e13e7a41`, merge commit em `main` |
| CI pós-merge | run `31285547886`, evento `push`, SHA exato do merge, 11/11 incluindo `CI required` |
| Fronteira | branch remota preservada; nenhuma tag remota; F3.8 não iniciada |

## 5. Tarefa ativa

Não há tarefa nem implementação ativa. Leia a [DEC-013](docs/decisions/DEC-013-fase3-ordem-operacional.md),
a [DEC-014](docs/decisions/DEC-014-reconciliacao-pos-merge.md) e a Fase 3 do plano antes de continuar.

A próxima tarefa planejada é F3.8 — edição real confinada — porque F3.4, F3.6 e F3.5 foram promovidas.
F3.7 permanece dependente de F4.7. O dossiê F3.8 ainda não existe e seu escopo não está congelado;
merge/CI anteriores, esta reconciliação ou autorizações antigas não permitem iniciar implementação.

## 6. Bloqueios atuais

Não há blocker técnico ou documental conhecido da F3.5 após esta certificação. A F3.8 permanece
bloqueada somente porque não foi autorizada nem possui dossiê/checkpoint `READY`. Terminal operacional,
Serena real, edição, promoção e F3.7 continuam sujeitos aos gates correspondentes.

## 7. Próxima ação exata

```text
PERMANECER PAUSADO, SEM IMPLEMENTAÇÃO:
1. Aguardar a autorização nominal “Autorizo iniciar a F3.8.”
2. Depois da autorização, comprovar o último head/CI de main, criar branch exclusiva F3.8 e preparar
   problema, baseline, escopo, aceite, rollback, executor e checkpoint READY antes do primeiro código.
3. Qualquer divergência exige parar e recongelar; a autorização não inclui push, PR ou merge.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Confirme que não existe dossiê ativo; consulte o último dossiê promovido somente quando necessário.
3. Leia a fase relevante no plano principal, DEC-013 e DEC-014.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e CI da `main`.
5. Execute somente a próxima ação exata; se escopo/estado divergir, pare e recongele o dossiê.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-08 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
