# Auditoria do Ciclo de Vida Agentic — Desejado vs. Implementado

> **Status da auditoria: Protótipo / Em desenvolvimento**

A matriz abaixo classifica efeitos observáveis no código atual. “Experimental” significa que existe
estrutura executável ou teste, mas a etapa ainda depende de simulação, sequência fixa ou garantia
incompleta. “Planejada” aponta para a fase responsável no plano operacional.

| Etapa | Componente atual | Evidência existente | Estado real | Lacuna para o produto |
|---|---|---|---|---|
| Disparo | CLI `run` | Cria `execution_id` e chama o runtime | Experimental | Falta validar repositório, configuração e precondições fail-closed |
| Contexto | `ContextAssembler` | Persiste `context.json` | Experimental | Score é heurístico; contexto estrutural/semântico real fica para F4 |
| Plano | `Planner` | Persiste `plan.json` | Experimental | Não nasce de provider real nem governa efeitos com pre/postcondições completas |
| Agente/modelo | `AgentExecutor`, `ModelRouter` e adapters | OpenAI Responses e endpoint local fazem HTTP real quando configurados | Primitiva real/injetável | CLI/lifecycle padrão não seleciona backend; integração live é opt-in e Anthropic falha como indisponível |
| Ferramentas | `ToolRouter` e factory operacional | Policy, dispatch durável e oito registrations opt-in possuem testes | Primitiva real/injetável | Lifecycle padrão não constrói o registry nem injeta worktree/adapters; ausência de backend falha fechada |
| Verificação | `VerificationEngine` | Executa subprocessos para gates selecionados | Experimental | Lista vazia pode passar; política fail-closed e gates completos ficam para F4 |
| Reparo | Retry do `GraphExecutor` | Consome erro, tool call, saída redigida, gates, diff e orçamento | Implementado como contrato | Sem composição operacional das tools ainda não produz um reparo de produto de ponta a ponta |
| Aprovação | Lifecycle/FSM | Solicitação, decisão e bundle de retomada são persistidos | Implementada como contrato | Aprovação exige `resume` explícito e ainda não aciona promoção Git segura |
| Promoção | `PromotionManager` | Registra evento e retorna string | Simulado | Runtime força dry-run e recebe SHA sintético; caminho live possui fallbacks sintéticos |
| Memória | `PythonAstIndexer` + `CodebaseMemoryAdapter` + `SnapshotManager` | Rebuild AST de blobs Python do commit exato e snapshot canônico com SHA/schema/status/digest validados | Backend local implementado | Execução é explícita por `harness index`; lifecycle, suficiência F4.3 e backend MCP ainda não o compõem automaticamente |
| Knowledge sync | `KnowledgeSynchronizer` | Transação local em etapas | Experimental | Falta integrar backend real, idempotência/recovery e política no caminho crítico |
| Evidência | `RuntimeEngine` e audit trail | `evidence.json` e hash chain locais | Experimental | Evidência pode registrar SHA/efeitos simulados e não prova alteração entregue |
| Rollback | `RollbackManager` | Eventos de compensação e adapter Git legado existem | Experimental/inseguro | Não usa o worktree real nem o terminal tipado atual; promoção, recovery e gates pós-reversão faltam |
| Doctor | `HealthProbe` | Formato de seis estágios e relatório | Simulado | Todos os estágios retornam OK sem probe; F6 |

## Interpretação correta dos testes

Os testes atuais provam providers HTTP com servidores controlados, tool loop durável, worktree Git
real, terminal por `argv`, edição confinada e transporte MCP Serena contra fixtures. Integrações live
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
