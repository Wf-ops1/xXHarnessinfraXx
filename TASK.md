# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. Não há dossiê ativo de implementação; a última promoção certificada está no
   [dossiê F3.8](docs/tasks/completed/F3.8.md).
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
| **Fase concluída** | Fase 2; F3.1–F3.6, F3.8 e corretivas F3.C1/F3.C2 promovidas; F3.7 permanece após F4.7 |
| **Fase ativa** | Pausa de reconciliação entre F3.8 promovida e F4.1 planejada |
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.1 ainda não possui gate nem branch de implementação |
| **Gate** | F3.8 `PROMOTED`; nenhum gate `READY`; reconciliação administrativa local em curso |
| **Executor ativo** | `Codex`, único escritor da reconciliação documental |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/promote-f3.8`, local e não publicada; PR administrativo ainda não aberto |
| **Baseline promovido** | F3.8 no merge `e6b5b84`; run pós-merge `31295594376`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F3.8` — edição real confinada e Serena MCP explícito, agora `PROMOTED` e arquivada |
| PR | #29; head final `f941c89fd0ec112aca82621ab9e11244f05962aa`; 11/11 no run `31292195340` |
| Merge | `e6b5b84bbe8299f8e04b9ad28c0ca0a86269c98f`, merge commit em `main` |
| CI pós-merge | run `31295594376`, evento `push`, SHA exato do merge, 11/11 incluindo `CI required` |
| Reconciliação | branch local `docs/promote-f3.8`; publicação e PR administrativo aguardam autorização própria |
| Fronteira | branch remota de implementação preservada; nenhuma tag remota; F4.1 não foi iniciada |

## 5. Tarefa ativa

Não há nenhuma tarefa ativa de implementação. O [dossiê F3.8](docs/tasks/completed/F3.8.md) preserva
o problema inicial, as evidências negativas R1/R2, os reparos sem relaxamento e a certificação final
do PR #29. O merge `e6b5b84` e o run pós-merge `31295594376` comprovam a promoção em `main`.

A branch `docs/promote-f3.8` executa somente a reconciliação administrativa exigida pela DEC-014:
arquiva o dossiê, atualiza painel, README, ledger e regressões de estado. Produto, dependências,
schemas, defaults e CI permanecem fora do escopo e devem ficar byte-idênticos ao merge.

F4.1 é apenas a próxima implementação planejada. Ela não pode receber dossiê `READY`, branch ou
edição antes do merge/CI do PR administrativo e de nova autorização nominal. F3.7 permanece depois
da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico conhecido na F3.8: PR, merge e CI pós-merge estão verdes. O bloqueio é
processual e intencional: a reconciliação administrativa ainda precisa ser validada, commitada,
publicada, revisada e mesclada com autorizações próprias. Até sua CI pós-merge verde, F4.1 permanece
bloqueada. Tags não serão publicadas.

## 7. Próxima ação exata

```text
CONCLUIR E VALIDAR LOCALMENTE A RECONCILIAÇÃO `docs/promote-f3.8`; PERMANECER PAUSADO.
Depois do commit local, a próxima autorização nominal será: “Autorizo publicar a branch
docs/promote-f3.8 e abrir o PR administrativo.” Após 11/11 checks no head desse PR, seu merge exigirá
outra autorização nominal. Depois do merge administrativo, validar CI `push` no SHA exato de `main`,
sincronizar e pedir autorização nova para iniciar F4.1. F3.7 permanece depois da F4.7. Não publicar
tags, excluir branches ou iniciar outra tarefa implicitamente.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia a certificação em `docs/tasks/completed/F3.8.md`.
3. Leia F4.1 no plano principal, DEC-013 e DEC-014.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e CI da `main`.
5. Enquanto a reconciliação estiver pendente, execute somente a próxima ação exata acima; não crie
   gate F4.1. Se escopo ou estado divergir, pare e registre nova evidência.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-09 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
