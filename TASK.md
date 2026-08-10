# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê de implementação ativo; a última promoção certificada é a
   [F4.2](docs/tasks/completed/F4.2.md).
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
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.3 permanece planejada e não iniciada |
| **Gate** | F4.2 `PROMOTED`; reconciliação administrativa concluída localmente e pendente de publicação |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f4.2`, somente local; checkpoint `checkpoint/f4.2-promotion-sync-ready` em `d515b70` |
| **Baseline promovido** | `main == origin/main == 212a9bf`; run `31345231098`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.2` — indexador Python AST local e vinculado ao commit, promovida e arquivada |
| PR de implementação | #34; head final `2268f3fa276b017ad5b64efdb54e7abbf1f917d9`; 11/11 no run `31344668587` |
| Promoção da implementação | merge `212a9bfba2189ce8ca84d8eca76ede2d872b7d2c`; run `31345231098`, 11/11 |
| Reconciliação administrativa | `docs/promote-f4.2`, somente local; publicação e PR administrativo pendentes de autorização |
| Fronteira | branch remota de implementação preservada; nenhuma tag remota ou exclusão de ref; F4.3/F3.7 não iniciadas |

## 5. Tarefa ativa

Não há implementação ativa. A F4.2 foi incorporada pelo PR #34, certificada no
[dossiê concluído](docs/tasks/completed/F4.2.md) e arquivada nesta reconciliação administrativa.
`PythonAstIndexer` faz rebuild dos blobs `.py` do commit Git exato e `harness index` publica/recarrega
o snapshot íntegro F4.1. Incrementalidade, MCP e suficiência por evidência permanecem fora desse escopo.

A F4.3 é a próxima tarefa planejada, mas não possui gate nem autorização e não pode começar antes do
merge do PR administrativo desta reconciliação e de sua CI pós-merge verde. F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico conhecido. A pendência é administrativa: publicar `docs/promote-f4.2` e
abrir seu PR documental exigem autorização nominal nova. O merge desse futuro PR, tags remotas e
exclusão de refs continuam não autorizados; F4.3 permanece bloqueada.

## 7. Próxima ação exata

```text
PAUSAR COM A RECONCILIAÇÃO F4.2 SOMENTE LOCAL. A PRÓXIMA AUTORIZAÇÃO EXATA É PUBLICAR
`docs/promote-f4.2` E ABRIR O PR ADMINISTRATIVO. Não iniciar F4.3/F3.7, publicar tag, excluir refs
ou mesclar qualquer PR sem autorização nominal própria.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/completed/F4.2.md` e a DEC-014 integralmente.
3. Confirme que F4.3 permanece apenas planejada e sem gate.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e CI da `main`.
5. Execute somente a próxima ação exata acima. Se escopo ou estado divergir, pare, registre a nova
   evidência e recongele antes de editar implementação.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-09T21:48:40-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
