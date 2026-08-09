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
| **Fase ativa** | Pausa entre o fechamento certificado da F3.8 e a F4.1 planejada |
| **Tarefa ativa** | Nenhuma tarefa ativa; F4.1 ainda não possui gate nem branch de implementação |
| **Gate** | F3.8 `PROMOTED`; PR administrativo #30 incorporado e verde; nenhum gate `READY` |
| **Executor ativo** | `Codex`, único escritor da correção documental transversal solicitada |
| **Workspace** | `C:\Users\walla\OneDrive\Desktop\ai-engineering-harness` |
| **Branch** | `docs/align-phase3-closeout`, somente documental; nenhuma branch de implementação ativa |
| **Baseline promovido** | `main == origin/main == c2aa89b`; run `31316853244`, evento `push`, 11/11 verde |
| **Python** | `.\.venv\Scripts\python.exe` — 3.12.13 |
| **uv** | `.\build\f0.6-tools\uv\bin\uv.exe` — 0.11.32 |

## 4. Última promoção comprovada

| Evidência | Resultado |
|---|---|
| Tarefa | `F3.8` — edição real confinada e Serena MCP explícito, agora `PROMOTED` e arquivada |
| PR de implementação | #29; head final `f941c89fd0ec112aca82621ab9e11244f05962aa`; 11/11 no run `31292195340` |
| Promoção da implementação | merge `e6b5b84bbe8299f8e04b9ad28c0ca0a86269c98f`; run `31295594376`, 11/11 |
| PR administrativo | #30; head final `bd0bda9385db850208f125e69757118ee9fe2b27`; 11/11 no run `31316549732` |
| Fechamento administrativo | merge `c2aa89b50ad32dc90b26b70087dbd795e32f0042`; run `31316853244`, 11/11 |
| Fronteira | branch remota de implementação preservada; nenhuma tag remota; F4.1 não foi iniciada |

## 5. Tarefa ativa

Não há nenhuma tarefa ativa de implementação. O [dossiê F3.8](docs/tasks/completed/F3.8.md) preserva
o problema inicial, as evidências negativas R1/R2, os reparos sem relaxamento, a promoção do PR #29
e o fechamento administrativo pelo PR #30. O merge `c2aa89b` e o run pós-merge `31316853244`
comprovam o baseline corrente de `main`.

A branch `docs/align-phase3-closeout` corrige o atraso documental encontrado após esse fechamento:
atualiza somente painel, README, ledger, dossiê arquivado e regressões de estado. Trata-se de correção
transversal explicitamente solicitada, não de reconciliação administrativa recursiva. Produto,
dependências, schemas, defaults e CI permanecem fora do escopo e byte-idênticos a `c2aa89b`.

F4.1 é apenas a próxima implementação planejada. Ela não pode receber dossiê `READY`, branch ou
edição antes do fechamento desta correção documental e de nova autorização nominal. F3.7 permanece
depois da F4.7.

## 6. Bloqueios atuais

Não há bloqueio técnico conhecido na F3.8: implementação, reconciliação administrativa e respectivas
CIs pós-merge estão verdes. O único trabalho corrente é a correção documental transversal solicitada
após a varredura. Até seu fechamento e uma autorização nominal nova, F4.1 permanece planejada e sem
gate. Tags não serão publicadas.

## 7. Próxima ação exata

```text
CONCLUIR E VALIDAR A CORREÇÃO DOCUMENTAL `docs/align-phase3-closeout`; PERMANECER PAUSADO.
Publicação/abertura e merge de seu único PR documental exigem autorizações próprias. Depois desse
fechamento, a próxima autorização nominal de implementação será: “Autorizo iniciar a F4.1.”
F3.7 permanece depois da F4.7. Não publicar tags, excluir branches ou iniciar outra tarefa
implicitamente.
```

## 8. Retomada após perda de contexto

1. Leia este arquivo integralmente.
2. Leia a certificação em `docs/tasks/completed/F3.8.md`.
3. Leia F4.1 no plano principal, DEC-013 e DEC-014.
4. Confirme `.git`, branch, `git status --short --branch`, `git log -10` e CI da `main`.
5. Enquanto a correção documental estiver pendente, execute somente a próxima ação exata acima; não
   crie gate F4.1. Se escopo ou estado divergir, pare e registre nova evidência.

## 9. Regras de manutenção

- limite máximo: 300 linhas;
- resultados, arquivos, comandos e rollback detalhados ficam no dossiê ativo;
- após promoção, arquivar o dossiê em `docs/tasks/completed/` e atualizar o índice;
- correção de dossiê concluído exige mudança documental explícita; nunca reescrever evidência silenciosamente;
- PR, CI, merge ou SHA só são registrados depois de observados.

---

*Atualizado em: 2026-08-09 | Fonte normativa: plano principal + DEC-012 + DEC-013 + DEC-014*
