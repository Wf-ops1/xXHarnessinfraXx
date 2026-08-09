# Auditoria Técnica da Estrutura, Fluxos e Pendências

> **Status: diagnóstico do protótipo; não é certificação operacional**

## 1. Método

A auditoria considera uma capacidade existente somente quando o código produz o efeito declarado e
há teste correspondente. Nomes de classes, YAMLs, diagramas e estados da FSM são evidência de design,
mas não substituem conectividade, isolamento, side effects reais ou falha segura.

## 2. Consistência da estrutura

| Item documentado anteriormente | Estado observado | Correção |
|---|---|---|
| `task.md` | O arquivo rastreado é `TASK.md` | Referências normalizadas |
| `contracts/` na raiz | Ausente | Contratos reais ficam em `src/ai_engineering_harness/contracts/` |
| `policies/` na raiz | Ausente | Defaults ficam em `src/ai_engineering_harness/defaults/policies/` |
| `graphs/specs/` na raiz | Ausente | Defaults ficam no pacote; specs locais ficam sob `.harness/` após init |
| `observability/log_integrity.py` | Ausente | Integridade está em `observability/audit.py` |
| Contagem fixa de testes | Ficava obsoleta após cada fase | Relatórios agora registram o checkpoint a que a contagem pertence |

## 3. FSM observada

Os estados e transições estão implementados em
[state_machine.py](../src/ai_engineering_harness/runtime/state_machine.py). O caminho principal atual
é:

```text
INITIATED
  -> CONTEXT_ASSEMBLING
  -> GENERATING_PLAN
  -> EXECUTING
  -> VERIFYING
  -> (EXECUTING/VERIFYING em retry)
  -> AWAITING_APPROVAL ou PROMOTING
  -> REINDEXING
  -> KNOWLEDGE_SYNC
  -> GENERATING_EVIDENCE
  -> COMPLETED
```

O grafo acima descreve a FSM legada, não o fluxo padrão atual da CLI nem efeitos garantidos. O
lifecycle canônico percorre arestas compiladas, persiste bundle/eventos e retoma por identidade; com o
registry padrão vazio, `harness run` falha fechado antes de modelo ou tool. `PromotionManager` ainda
pode produzir SHA de dry-run. O `CodebaseMemoryAdapter` permanece separado do lifecycle, mas agora
resolve um commit Git real e só serve snapshot `ready` canônico com digest válido; ausência falha
explicitamente e a geração AST continua pendente na F4.2.

## 4. Matriz de comandos

| Comando | Código existe | Efeito real comprovado | Classificação |
|---|---:|---:|---|
| `harness init` | Sim | Cria/copia scaffold local | Implementado como base |
| `harness doctor` | Sim | Apenas renderiza resultados pré-aprovados | Simulado |
| `harness compile` | Sim | Compila pelo pipeline canônico e grava artefato validado | Implementado como contrato interno |
| `harness index` | Sim | Valida/carrega o snapshot do SHA Git atual; falha se estiver ausente/inválido | Parcial/fail-closed até a F4.2 |
| `harness run` | Sim | Cria bundle e falha fechado sem executor injetado | Experimental/fail-closed |
| `harness status` | Sim | Lê arquivo de estado | Implementado como leitura local |
| `harness inspect` | Sim | Lê estado, audit e aprovação | Experimental |
| `harness approve` | Sim | Persiste decisão | Parcial; não retoma o fluxo |
| `harness resume` | Sim | Retoma do bundle canônico | Implementado como contrato injetável |
| `harness verify` | Sim | Executa subprocessos selecionados | Experimental |
| `harness audit` | Sim | Valida hash chain local | Implementado como mecanismo local |
| `harness rollback` | Sim | Eventos locais e Git opcional | Experimental/inseguro |

## 5. Riscos prioritários

| Prioridade | Risco | Causa atual | Fase responsável |
|---|---|---|---|
| P0 | Alteração fora de isolamento | Worktree/guard/edição reais ainda não são compostos automaticamente pelo lifecycle | F4/F5 |
| P0 | Git mutável fora do protocolo | Promoção/rollback legados não usam candidate commit, worktree e terminal tipado | F3.7/F6 |
| P0 | Sucesso sem efeito | CLI falha fechada, mas promoção e memória isoladas ainda aceitam resultados sintéticos | F3.7/F4/F6 |
| P0 | Diagnóstico enganoso | Doctor retorna saudável incondicionalmente | F6.5 |
| P1 | Primitivas não compostas | Lifecycle padrão não injeta provider, tools, worktree ou gates | F4/F5 |
| P1 | Aprovação sem promoção segura | Resume existe; candidate commit e promoção ainda faltam | F3.7/F5 |
| P1 | Evidência insuficiente | Pode registrar identificadores sintéticos | F6/F7 |
| P1 | CI ainda não cobre comportamento operacional completo | Pipeline cobre providers/paths/worktree/terminal/edição como primitivas, não sua composição com promoção e recovery | F4–F7 |

## 6. Gates para considerar o produto operacional

- instalação em ambiente limpo e em repositório externo;
- nenhum adapter simulado registrado no runtime;
- doctor falha quando dependência real estiver ausente;
- toda escrita ocorre dentro de worktree criado por Git;
- comando de ferramenta usa argv, allowlist, cwd confinado e `shell=False`;
- gate obrigatório não executado bloqueia;
- aprovação pausa e retoma após reinício;
- promoção produz candidate SHA e promoted SHA reais;
- rollback usa `git revert` e reexecuta gates;
- E2E cobre sucesso, falha, retry, resume, promoção e rollback sem mocks;
- CI Windows/Linux e artefato de release validados.

Os critérios completos estão no
[plano de implementação](plano_implementacao_harness_operacional.md).
