# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é [F4.2](docs/tasks/active/F4.2.md); a última promoção certificada é a
   [F4.1](docs/tasks/completed/F4.1.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8, F4.1 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Fase 4 — contexto estrutural, planejamento e gates baseados em evidência |
| **Tarefa ativa** | F4.2 — indexador Python AST local e vinculado ao commit |
| **Gate** | F4.2 `READY`; lifecycle `ACTIVE`; implementação local autorizada |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f4.2-python-ast-indexer`, somente local; checkpoint `checkpoint/f4.2-ready` pendente do primeiro commit |
| **Baseline promovido** | `main == origin/main == 571a8eb`; run `31329231458`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F4.1` — armazenamento íntegro do índice estrutural, promovida e arquivada |
| PR de implementação | #32; head final `3ba0e254d9d7425113ffcbcd6d22b5c663d7255e`; 11/11 no run `31322494169` |
| Promoção da implementação | merge `12ce3b7360a6035fb354326261fc409de15e29ec`; run `31323952381`, 11/11 |
| PR administrativo | #33; head final `e1ecc39cf26df1a4267aef867829b6d71f8bda1f`; 11/11 no run `31328946696` |
| Fechamento administrativo | merge `571a8eb8be27179dd83527d7691012d732a27d28`; run `31329231458`, 11/11 |
| Fronteira | branches remotas anteriores preservadas; nenhuma tag remota ou exclusão de ref; F4.3/F3.7 não iniciadas |

## 5. Tarefa ativa

A F4.2 está `READY` no [dossiê ativo](docs/tasks/active/F4.2.md). O baseline comprovou que
`harness index` apenas procura snapshot pré-existente e falha no SHA atual; não existe backend AST, e
testes de fase ainda gravam snapshots vazios manualmente.

O escopo congelado implementa rebuild completo dos blobs `.py` do commit Git exato usando `ast`,
produz módulos, classes, funções/métodos e imports no contrato F4.1 e torna `harness index` o produtor
explícito. Working tree, incrementalidade, MCP, suficiência F4.3 e F3.7 permanecem fora do escopo.
F3.7 permanece depois da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico conhecido. O baseline focado passou `32 passed`; o gate está congelado e a
implementação local pode começar depois do checkpoint. Push, PR, merge, tags e exclusão de refs não
foram autorizados. Qualquer ampliação fora da allowlist exige pausa e recongelamento.

## 7. Próxima ação exata

```text
CRIAR O COMMIT/TAG LOCAL `checkpoint/f4.2-ready` E IMPLEMENTAR SOMENTE O INDEXADOR AST CONGELADO,
CLI, TESTES E DOCUMENTAÇÃO AFETADA. Não iniciar F4.3/F3.7 nem publicar branch/tag, abrir/mesclar PR
ou excluir refs sem autorização nominal própria.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia `docs/tasks/active/F4.2.md` integralmente.
3. Leia F4.2 no plano principal e as fronteiras F4.1/F4.3.
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

*Atualizado em: 2026-08-09T16:06:14-03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
