# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê de implementação ativo; a última promoção certificada é a
   [F4.4](docs/tasks/completed/F4.4.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.4 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.5 permanece planejada e não iniciada |
| **Gate** | F4.4 `PROMOTED`; reconciliação administrativa local pronta, publicação pendente |
| **Última promoção** | F4.4 `PROMOTED` pelo PR #38; reconciliação local em `docs/promote-f4.4` |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.4`, somente local, sem upstream |
| **Baseline promovido** | `main == origin/main == 93ce4ce`; run `31445624269`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.4` — plano tipado e específico, promovida e arquivada localmente |
| PR de implementação | PR #38; head final `fbdb6ee3d2e1728cbc691b98f04846989475c614`; 11/11 no run `31442203348` |
| Promoção da implementação | merge `93ce4ce9f4f0042c58d64103528b6c359a475bd9`; run `31445624269`, 11/11 |
| Reconciliação administrativa | branch local `docs/promote-f4.4`, sem upstream; publicação e PR ainda não autorizados |
| Fronteira | branches remotas preservadas; nenhuma tag publicada ou exclusão de ref; F4.5/F3.7 não iniciadas |

## 5. Tarefa ativa

Não há implementação ativa. A F4.4 foi incorporada pelo PR #38 e certificada no
[dossiê concluído](docs/tasks/completed/F4.4.md). `PlanDocument` é Pydantic estrito/frozen/versionado;
o lifecycle liga contexto, plano e entrada por digest, persiste `PLAN_GENERATION_STARTED`, payload,
`plan.json` e `PLAN_GENERATED` antes do primeiro nó e recupera o mesmo plano no resume sem nova chamada.

A F4.5 é a próxima tarefa planejada: normalizar IDs de gates conforme a Fase 4 e a
[DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md). Seu gate não pode ser preparado nem
sua implementação iniciada antes de a reconciliação administrativa F4.4 ser publicada, mesclada e
ficar verde em `main`. F4.6–F4.8, MCP e memória semântica continuam fora do escopo. F3.7 permanece depois
da F4.7.

## 6. Bloqueios atuais

Não há blocker técnico conhecido na F4.4. A pendência é exclusivamente administrativa: publicar
`docs/promote-f4.4`, abrir seu PR documental, observar checks, obter autorização separada de merge e
confirmar a CI pós-merge. Até lá, F4.5/F3.7 permanecem bloqueadas. Publicação de tag e exclusão de refs
permanecem proibidas.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL EXPLÍCITA PARA PUBLICAR docs/promote-f4.4 E ABRIR SEU PR ADMINISTRATIVO.
NÃO PUBLICAR TAG, MESCLAR PR, EXCLUIR REFS OU INICIAR F4.5/F3.7 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/completed/F4.4.md`, DEC-015, DEC-014, as seções 1.1–1.2 e a Fase 4 do plano integralmente.
3. Confirme F4.4 `PROMOTED`, PR #38, head `fbdb6ee`, merge `93ce4ce` e runs
   `31442203348`/`31445624269`.
4. Confirme `.git`, `docs/promote-f4.4`, `git status --short --branch`, `git log -10` e o baseline de `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T21:25:21-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
