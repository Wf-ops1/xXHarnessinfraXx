# TASK.md — AI Engineering Harness · Painel Operacional

> **Função:** estado corrente e retomada rápida. Histórico detalhado não pertence a este arquivo.
> Nunca marque uma tarefa como concluída sem executar seu aceite e comprovar o estado remoto observado.

## 1. Fontes de verdade

1. Este painel: fase, coordenação, tarefa ativa, bloqueios e próxima ação.
2. O único dossiê ativo é [F3.8](docs/tasks/active/F3.8.md); a última promoção certificada está no
   [dossiê F3.5](docs/tasks/completed/F3.5.md).
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
| **Fase concluída** | Fase 2 — F2.1–F2.6 implementadas e promovidas |
| **Fase ativa** | Fase 3 — paths, ferramentas e workspace reais |
| **Tarefa ativa** | F3.8 — edição real confinada e Serena MCP explícito |
| **Gate** | `READY / ACTIVE` |
| **Executor ativo** | `Codex`, único escritor |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `task/f3.8-real-editing`, criada de `fd49310ddca91e10381a08a7f456fe9ab03d3636` |
| **Baseline promovido** | F3.5 em `b6a4a24`; reconciliação PR #28 em `fd49310`; run `31287059584`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32; somente `mcp>=1.26,<2` congelada para F3.8 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F3.5` — terminal seguro por `argv`, agora `PROMOTED` e arquivada |
| PR | #27; head final `e6d947a2713e61c0700154cb7453f8bc0a7c342f`; 11/11 no run `31284043501` |
| Merge | `b6a4a24179271a8caa22252f71d08c35e13e7a41`, merge commit em `main` |
| CI pós-merge | run `31285547886`, evento `push`, SHA exato do merge, 11/11 incluindo `CI required` |
| Reconciliação | PR administrativo #28; merge `fd49310ddca91e10381a08a7f456fe9ab03d3636`; run `31287059584`, 11/11 |
| Fronteira | branches remotas preservadas; nenhuma tag remota; F3.8 iniciou somente após autorização nova |

## 5. Tarefa ativa

O [dossiê F3.8](docs/tasks/active/F3.8.md) comprovou o sucesso sintético do adapter legado, revalidou
F3.4/F3.6/F3.5/F3.C2 e congelou arquivos, efeitos, critérios e rollback antes do primeiro código.

A entrega implementa leitura/listagem/busca/patch locais confinados, adapta o terminal seguro e Git
somente leitura ao registry opt-in e substitui o falso Serena por cliente MCP configurado
explicitamente. Lifecycle/CLI, configuração default, promoção F3.7 e fallback automático estão fora.

## 6. Bloqueios atuais

Não há blocker conhecido no gate congelado. A consulta `git ls-remote` foi negada pela rede do sandbox,
mas a sessão autenticada do GitHub revalidou o run `31287059584` como `push/main/fd49310`, 11/11
verde; Git local comprovou divergência `0 0` antes da branch. Qualquer evidência negativa posterior
reabre o aceite e bloqueia publicação.

## 7. Próxima ação exata

```text
EXECUTAR SOMENTE O ESCOPO CONGELADO DA F3.8:
1. Criar o commit/tag local checkpoint/f3.8-ready antes do primeiro arquivo de implementação.
2. Implementar e executar todo o aceite do dossiê; falha exige reparar sem enfraquecer critérios ou
   parar/recongelar se houver expansão material.
3. Ao ficar verde, registrar COMPLETED_LOCAL / PROMOTION_PENDING e pausar. A autorização atual não
   inclui push, PR, merge, exclusão de refs, configuração live de Serena ou início da F3.7.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia integralmente o único dossiê ativo `docs/tasks/active/F3.8.md`.
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

*Atualizado em: 2026-08-08 22:16 -03:00 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
