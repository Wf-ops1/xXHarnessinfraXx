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

Para artefatos com a policy F4.3, o prefixo real agora é
`INITIATED → CONTEXT_ASSEMBLING → PLANNING → EXECUTING`; insuficiência desvia para
`BLOCKED_INSUFFICIENT_CONTEXT`, pré-requisito inválido para `BLOCKED_PREREQUISITE` e uma quarta
solicitação após três decisões persistidas leva a `FAILED_RETRY_EXHAUSTED`. O grafo maior acima
descreve a FSM legada, não o fluxo padrão atual da CLI nem efeitos garantidos. O lifecycle canônico
percorre arestas compiladas, persiste bundle/eventos e retoma por identidade; com o
registry padrão vazio, `harness run` falha fechado antes de modelo ou tool. `PromotionManager` ainda
pode produzir SHA de dry-run. O `PythonAstIndexer` também permanece separado do lifecycle, mas
`harness index` agora resolve o commit Git real, lê seus blobs `.py`, produz símbolos AST e publica um
snapshot `ready` canônico. O `CodebaseMemoryAdapter` somente serve esse snapshot com digest válido;
consulta ausente/inválida continua falhando explicitamente, sem indexação implícita.

Na implementação local F4.4, `PLANNING → EXECUTING` somente ocorre depois de contexto suficiente relido,
structured output tipado, payload content-addressed, projeção `plan.json` atômica e evento
`PLAN_GENERATED`. Resume recupera o payload sem nova chamada; efeito iniciado sem outcome, tamper,
duplicata ou divergência de policy/input bloqueiam antes do primeiro nó. Essa mudança está consolidada
no commit local, mas ainda não foi publicada nem promovida.

## 4. Matriz de comandos

| Comando | Código existe | Efeito real comprovado | Classificação |
|---|---:|---:|---|
| `harness init` | Sim | Cria/copia scaffold local | Implementado como base |
| `harness doctor` | Sim | Apenas renderiza resultados pré-aprovados | Simulado |
| `harness compile` | Sim | Compila pelo pipeline canônico e grava artefato validado | Implementado como contrato interno |
| `harness index` | Sim | Faz rebuild AST dos blobs Python do SHA Git atual, publica e recarrega snapshot íntegro | Implementado localmente; explícito, Python-only e ainda fora do lifecycle |
| `harness run` | Sim | Cria bundle e falha fechado sem executor injetado | Experimental/fail-closed |
| `harness status` | Sim | Lê arquivo de estado | Implementado como leitura local |
| `harness inspect` | Sim | Lê estado, audit e aprovação | Experimental |
| `harness approve` | Sim | Persiste decisão | Parcial; não retoma o fluxo |
| `harness resume` | Sim | Retoma do bundle canônico | Implementado como contrato injetável |
| `harness verify` | Sim | Carrega worktree validado, resolve configuração/argv e executa gates selecionados | Experimental; persistência e decisão final ainda faltam |
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
| P0 | Verificação incompleta | F4.5/F4.6 bloqueiam suíte inválida e pré-requisito ausente, mas a CLI reprovada ainda pode retornar zero e não existe resultado persistido/commit-bound | F4.7 |
| P1 | Resolução ainda não promovida | A CI R3 do PR #44 repetiu a perda do venv; o reparo precisa selecionar por `sys.prefix` e impedir nova dereferência no `TerminalAdapter` | F4.6; promoção bloqueada |
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
