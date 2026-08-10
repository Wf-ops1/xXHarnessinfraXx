# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê de implementação ativo; a última promoção certificada é a
   [F4.3](docs/tasks/completed/F4.3.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1–F4.3 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.4 permanece planejada e não iniciada |
| **Gate** | F4.3 `PROMOTED`; reconciliação administrativa local pronta, publicação pendente |
| **Última promoção** | F4.3 `PROMOTED` pelo PR #36; reconciliação local em `docs/promote-f4.3` |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.3`, somente local; checkpoint `25f72b1`, sem upstream |
| **Baseline promovido** | `main == origin/main == fa31ef8`; run `31419214233`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.3` — context sufficiency baseada em evidência, promovida e arquivada localmente |
| PR de implementação | #36; head final `84eda1c421d13d1e8e86620127c3318e2cfe5086`; 11/11 no run `31414853048` |
| Promoção da implementação | merge `fa31ef8987b1028d38014fe676247cd425daf9b6`; run `31419214233`, 11/11 |
| Reconciliação administrativa | branch local `docs/promote-f4.3`; checkpoint `25f72b1`; publicação e PR ainda não autorizados |
| Fronteira | branches remotas preservadas; nenhuma tag remota ou exclusão de ref; F4.4/F3.7 não iniciadas |

## 5. Tarefa ativa

Não há implementação ativa. A F4.3 foi incorporada pelo PR #36 e certificada no
[dossiê concluído](docs/tasks/completed/F4.3.md). O lifecycle agora exige contexto suficiente baseado
em manifesto, evidência, snapshot e identidade antes do primeiro nó; tentativas e estados bloqueantes
são persistidos, e o retry de recuperação é limitado de forma durável.

A F4.4 é a próxima tarefa planejada: produzir e persistir `PlanDocument` tipado ligado aos digests de
contexto e plano conforme a [DEC-015](docs/decisions/DEC-015-composicao-canonica-fase4.md). Seu gate não
pode ser preparado nem sua implementação iniciada antes de a reconciliação administrativa F4.3 ser
publicada, mesclada e ficar verde em `main`. Gates F4.5–F4.8, F3.7, MCP e memória semântica continuam
fora do escopo; F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há blocker técnico local ou remoto aberto na F4.3. A pendência é exclusivamente administrativa:
publicar `docs/promote-f4.3`, abrir seu PR documental, observar checks, obter autorização separada de
merge e confirmar a CI pós-merge. Até lá, F4.4/F3.7 permanecem bloqueadas. Tags continuam somente
locais; publicação de tag e exclusão de refs permanecem proibidas.

## 7. Próxima ação exata

```text
AGUARDAR AUTORIZAÇÃO NOMINAL EXPLÍCITA PARA PUBLICAR docs/promote-f4.3 E ABRIR SEU PR ADMINISTRATIVO.
NÃO PUBLICAR TAG, MESCLAR PR, EXCLUIR REFS OU INICIAR F4.4/F3.7 SEM NOVA AUTORIZAÇÃO.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/completed/F4.3.md`, DEC-015, DEC-014 e a fase ativa do plano integralmente.
3. Confirme F4.3 `PROMOTED`, PR #36, merge `fa31ef8`, run `31419214233` e os sete checkpoints locais.
4. Confirme `.git`, `docs/promote-f4.3`, `git status --short --branch`, `git log -10` e o baseline de `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-10T17:32:05-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014 + DEC-015*
