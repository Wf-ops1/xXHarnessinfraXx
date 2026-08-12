# Auditoria do Ciclo de Vida Agentic — Desejado vs. Implementado

> **Status da auditoria: Protótipo / Em desenvolvimento**

A matriz abaixo classifica efeitos observáveis no código atual. “Experimental” significa que existe
estrutura executável ou teste, mas a etapa ainda depende de simulação, sequência fixa ou garantia
incompleta. “Planejada” aponta para a fase responsável no plano operacional.

| Etapa | Componente atual | Evidência existente | Estado real | Lacuna para o produto |
|---|---|---|---|---|
| Disparo | CLI `run` | Cria `execution_id` e chama o runtime | Experimental | Falta validar repositório, configuração e precondições fail-closed |
| Contexto | `ContextAssembler` + `ExecutionLifecycleService` | Policy compilada, seis dimensões `Decimal`, dual gate, identidade/digest e partição exata de evidência, `context.json`, evento por digest, estados bloqueantes e resume possuem testes | F4.3 `PROMOTED` | PR #36 e reconciliação #37 foram incorporados com CI pós-merge verde; a entrada ainda depende de artefatos e snapshot previamente produzidos |
| Plano | `Planner` + `ExecutionLifecycleService` | Contrato Pydantic versionado, structured output roteado, evidência/policies por digest, payload/projeção/eventos antes do nó e resume idempotente possuem testes positivos e fail-closed | F4.4 `PROMOTED` | Provider/configuração operacional continuam injetáveis; verificação e reparo posteriores já compõem o lifecycle, mas não tornam os backends automáticos |
| Agente/modelo | `AgentExecutor`, `ModelRouter` e adapters | OpenAI Responses e endpoint local fazem HTTP real quando configurados | Primitiva real/injetável | CLI/lifecycle padrão não seleciona backend; integração live é opt-in e Anthropic falha como indisponível |
| Ferramentas | `PolicyEngine`, `ToolRouter` e factory operacional | A F5.2 local avalia oito eixos com default-deny/deny-wins, pré-autoriza o lote e persiste regra + digest antes/depois do efeito; oito registrations opt-in fornecem operação/path reais | Primitiva real/injetável | Lifecycle padrão não constrói o registry nem injeta worktree/adapters; trust boundary F5.3 e aprovação content-bound F5.6 ainda não estão integrados |
| Verificação | `VerificationEngine` + `ExecutionLifecycleService` | F4.5 normaliza cinco IDs; F4.6 resolve a suíte no `ProvisionedWorktree`; F4.7 persiste resultados commit-bound e guarda `COMPLETED`; F4.8 executa targeted → full após reparo | F4.7/F4.8 `PROMOTED` | Provider e worktree permanecem injetados no E2E |
| Reparo | `ExecutionLifecycleService` + `GraphExecutor` | Reprovação F4.7 vira `RetryContext` redigido para o `on_failure` compilado; schedule, deadline e budgets são duráveis; crash-resume e limites possuem E2E | F4.8 `PROMOTED` | Sem composição automática das tools/worktree/provider, o caminho padrão ainda não executa reparo autônomo em repositório externo |
| Aprovação | Lifecycle/FSM | Solicitação, decisão e bundle de retomada são persistidos; F3.7 exige `ApprovalStatus.APPROVED` antes do efeito | Implementada como contrato | Aprovação exige `resume` explícito e ainda não é vinculada ao conteúdo/diff do candidate |
| Promoção | `PromotionManager` + `ExecutionLifecycleService` | Candidate real no worktree, full suite no mesmo SHA, write-ahead/outcome, cherry-pick único, dry-run e recovery possuem E2E | F3.7 `PROMOTED` | Composição permanece opt-in; CLI/defaults não constroem manager/provider automaticamente |
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
rejeição antes do terminal, inclusive do alias legado `tests`. Para F4.6/F4.7, provam detecção pela
configuração, resolução integral antes de subprocessos, worktree externo real, erro tipado de
pré-requisito e persistência canônica por gate. Para F4.8, provam commit quebrado → reparo → targeted
→ full, recuperação de cursor sem efeito duplicado e exaustão durável de todos os limites. Eles
provam providers HTTP com servidores controlados,
tool loop durável com decisão F5.2 persistida, worktree Git real, terminal por `argv`, edição confinada e transporte MCP Serena
contra fixtures. Integrações live
OpenAI/Serena continuam condicionadas a configuração externa. A F3.7 prova promoção segura sobre
repositório/worktree externos temporários, incluindo falhas e recovery, mas por composição explícita.
Eles ainda não provam que a CLI compõe todas as primitivas numa execução autônoma nem reversão segura.
O E2E atual usa diretórios temporários e backends determinísticos injetados; não cobre o gate final do
produto sem mocks.

## Gate para mudar uma linha para “implementada”

Uma etapa só muda para implementada quando:

1. o efeito real correspondente existir;
2. indisponibilidade gerar erro tipado e estado bloqueado;
3. side effects estiverem confinados e auditados;
4. houver teste de sucesso e de falha segura;
5. o E2E externo comprovar o comportamento sem mocks.
