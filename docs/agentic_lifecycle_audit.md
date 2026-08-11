# Auditoria do Ciclo de Vida Agentic — Desejado vs. Implementado

> **Status da auditoria: Protótipo / Em desenvolvimento**

A matriz abaixo classifica efeitos observáveis no código atual. “Experimental” significa que existe
estrutura executável ou teste, mas a etapa ainda depende de simulação, sequência fixa ou garantia
incompleta. “Planejada” aponta para a fase responsável no plano operacional.

| Etapa | Componente atual | Evidência existente | Estado real | Lacuna para o produto |
|---|---|---|---|---|
| Disparo | CLI `run` | Cria `execution_id` e chama o runtime | Experimental | Falta validar repositório, configuração e precondições fail-closed |
| Contexto | `ContextAssembler` + `ExecutionLifecycleService` | Policy compilada, seis dimensões `Decimal`, dual gate, identidade/digest e partição exata de evidência, `context.json`, evento por digest, estados bloqueantes e resume possuem testes | F4.3 `PROMOTED` | PR #36 e reconciliação #37 foram incorporados com CI pós-merge verde; a entrada ainda depende de artefatos e snapshot previamente produzidos |
| Plano | `Planner` + `ExecutionLifecycleService` | Contrato Pydantic versionado, structured output roteado, evidência/policies por digest, payload/projeção/eventos antes do nó e resume idempotente possuem testes positivos e fail-closed | F4.4 `PROMOTED` | Provider/configuração operacional continuam injetáveis; F4.7 ainda precisa persistir gates e guardar `COMPLETED`, e F4.8 compor retry |
| Agente/modelo | `AgentExecutor`, `ModelRouter` e adapters | OpenAI Responses e endpoint local fazem HTTP real quando configurados | Primitiva real/injetável | CLI/lifecycle padrão não seleciona backend; integração live é opt-in e Anthropic falha como indisponível |
| Ferramentas | `ToolRouter` e factory operacional | Policy, dispatch durável e oito registrations opt-in possuem testes | Primitiva real/injetável | Lifecycle padrão não constrói o registry nem injeta worktree/adapters; ausência de backend falha fechada |
| Verificação | `VerificationEngine` | F4.5 promovida normaliza cinco IDs; F4.6 detecta configuração, resolve a suíte inteira e valida executáveis no `ProvisionedWorktree` antes de efeitos | F4.6 R2 `REPAIR_ACTIVE / PROMOTION_BLOCKED` | PR #44 perdeu o venv ao dereferenciar o launcher POSIX; depois do reparo, F4.7 persiste/guarda conclusão e F4.8 compõe retry |
| Reparo | Retry do `GraphExecutor` | Consome erro, tool call, saída redigida, gates, diff e orçamento | Implementado como contrato | Sem composição operacional das tools ainda não produz um reparo de produto de ponta a ponta |
| Aprovação | Lifecycle/FSM | Solicitação, decisão e bundle de retomada são persistidos | Implementada como contrato | Aprovação exige `resume` explícito e ainda não aciona promoção Git segura |
| Promoção | `PromotionManager` | Registra evento e retorna string | Simulado | Runtime força dry-run e recebe SHA sintético; caminho live possui fallbacks sintéticos |
| Memória | `PythonAstIndexer` + `CodebaseMemoryAdapter` + `SnapshotManager` | Rebuild AST de blobs Python do commit exato e snapshot canônico com SHA/schema/status/digest validados; F4.3 consome o snapshot commit-bound | Backend local implementado | Execução do índice é explícita por `harness index`; o lifecycle não reindexa automaticamente e o backend MCP ainda não substitui esse backend |
| Knowledge sync | `KnowledgeSynchronizer` | Transação local em etapas | Experimental | Falta integrar backend real, idempotência/recovery e política no caminho crítico |
| Evidência | `RuntimeEngine` e audit trail | `evidence.json` e hash chain locais | Experimental | Evidência pode registrar SHA/efeitos simulados e não prova alteração entregue |
| Rollback | `RollbackManager` | Eventos de compensação e adapter Git legado existem | Experimental/inseguro | Não usa o worktree real nem o terminal tipado atual; promoção, recovery e gates pós-reversão faltam |
| Doctor | `HealthProbe` | Formato de seis estágios e relatório | Simulado | Todos os estágios retornam OK sem probe; F6 |

## Interpretação correta dos testes

Os testes atuais também provam o dual gate de contexto, bloqueio antes de nós, envelope imutável,
retry/exaustão e recuperação de decisão durável. Para F4.4, provam que plano tipado e ligado a
contexto/input é persistido antes do primeiro nó, que tamper/duplicata/policy/output/persistência
inválidos bloqueiam e que resume não repete o provider. Para F4.5, provam convergência da taxonomia e
rejeição antes do terminal, inclusive do alias legado `tests`. Para F4.6, provam detecção pela
configuração, resolução integral antes de subprocessos, worktree externo real e erro tipado de
pré-requisito. Eles provam providers HTTP com servidores controlados,
tool loop durável, worktree Git real, terminal por `argv`, edição confinada e transporte MCP Serena
contra fixtures. Integrações live
OpenAI/Serena continuam condicionadas a configuração externa. Eles ainda não provam que a CLI compõe
essas primitivas numa execução autônoma, nem promoção/reversão segura sobre um repositório externo. O
E2E atual usa diretórios temporários e backends determinísticos injetados; não cobre o gate final do
produto sem mocks.

## Gate para mudar uma linha para “implementada”

Uma etapa só muda para implementada quando:

1. o efeito real correspondente existir;
2. indisponibilidade gerar erro tipado e estado bloqueado;
3. side effects estiverem confinados e auditados;
4. houver teste de sucesso e de falha segura;
5. o E2E externo comprovar o comportamento sem mocks.
