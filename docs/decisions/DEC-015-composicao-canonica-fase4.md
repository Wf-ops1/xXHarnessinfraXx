# DEC-015 — Composição canônica e ownership da Fase 4

> **Estado:** aceita
> **Data:** 2026-08-10
> **Autoridade:** autorização explícita para reabrir e recongelar o gate F4.3 conforme a auditoria
> integral da Fase 4, sem iniciar implementação

## Contexto

A auditoria da Fase 4 comprovou que F4.1 e F4.2 entregam primitivas reais, mas contexto, planner e
verificação permanecem componentes separados. O E2E legado conclui o lifecycle antes de chamar o
`VerificationEngine` manualmente. Também foram reproduzidos três falsos sucessos: suíte vazia, gate
desconhecido e o ID `tests` da policy resultam em `all_passed=True` com `0/0`; a CLI retorna exit code
zero mesmo quando recebe uma suíte reprovada.

O primeiro gate F4.3, preservado pela tag `checkpoint/f4.3-ready`, corrigia o cálculo local, mas
proibia alterar o lifecycle e entregava apenas uma exceção classificada. Isso reduzia o requisito
normativo de que a insuficiência leve uma execução real a `BLOCKED_INSUFFICIENT_CONTEXT`. Nenhuma
tarefa posterior possuía ownership explícito da composição completa.

## Decisão

1. `ExecutionLifecycleService` é o owner canônico da preparação pré-grafo. `GraphExecutor` continua
   responsável somente por validar e percorrer nós/arestas do artefato compilado.
2. Um artefato que declara a policy tipada `context_sufficiency` exige um envelope de entrada estrito
   com exatamente `context_request` e `graph_input`. O bundle imutável persiste e calcula o digest do
   envelope completo; somente `graph_input` é validado contra o contrato do entrypoint e entregue ao
   `GraphExecutor`.
3. O lifecycle usa a cópia da policy resolvida no artefato compilado. Arquivo mutável procurado por
   path, threshold default e policy fora do bundle não podem decidir a execução.
4. Após preflight de `graph_input`, identidade Git e criação atômica do bundle/record, o lifecycle
   transiciona duravelmente `INITIATED → CONTEXT_ASSEMBLING` e chama o assembler.
5. O assembler calcula e persiste a decisão, mas nunca altera `ExecutionRecord`. Se qualquer lado do
   dual gate falhar, o lifecycle referencia o digest do relatório e transiciona sob o lock canônico
   para `BLOCKED_INSUFFICIENT_CONTEXT` antes de devolver o erro tipado.
6. Policy/snapshot corrompido, falha de persistência ou pré-requisito operacional inválido não são
   tratados como baixa confiança; levam a `BLOCKED_PREREQUISITE`. Nenhum nó do grafo é executado em
   qualquer estado bloqueado.
7. `resume` de `BLOCKED_INSUFFICIENT_CONTEXT` recarrega o mesmo envelope/bundle, transiciona novamente
   para `CONTEXT_ASSEMBLING` e cria uma nova decisão persistida. O limite de retrieval da policy é
   aplicado de forma durável; esgotamento leva a `FAILED_RETRY_EXHAUSTED`.
8. F4.4 estende a mesma preparação: somente após contexto suficiente o lifecycle entra em `PLANNING`,
   produz/persiste `PlanDocument` e entrega ao grafo uma entrada ligada aos digests de contexto e plano.
9. F4.5 normaliza IDs; F4.6 resolve comandos efetivos; F4.7 fornece o executor determinístico de
   verificação e o guard de conclusão. Nenhuma execução chega a `COMPLETED` sem resultado persistido
   para ao menos um gate obrigatório realmente executado no digest do commit verificado.
10. F4.8 consome exclusivamente os resultados F4.7 para criar `RetryContext`, reexecuta gates afetados
    somente quando seguro e exige a suíte completa antes da fronteira de promoção.
11. Cada tarefa atualiza os grafos/defaults que consomem seu contrato. Um componente correto mas não
    injetado não satisfaz a tarefa; composição não fica adiada para um gate sem ID.
12. A F4.3 não implementa planner, executor de gates, repair loop, promoção ou MCP. Ela entrega somente
    contexto determinístico, sua persistência e a transição real de preparação/bloqueio.

## Consequências para o gate F4.3 R2

- `execution_lifecycle.py`, o facade estritamente afetado, os defaults context-enabled e seus testes
  passam a integrar a allowlist F4.3;
- `GraphExecutor`, `ExecutionRecord` e a tabela da FSM não precisam mudar: os estados e transições
  exigidos já existem;
- o envelope é obrigatório apenas quando a policy de contexto está no artefato; grafos de testes sem
  essa policy preservam seu contrato F2;
- o checkpoint original não é movido nem apagado. O recongelamento recebe novo commit/tag
  `checkpoint/f4.3-r2-ready`;
- qualquer necessidade de mudar schema do bundle/record, compiler ou GraphExecutor reabre o gate.

## Alternativas rejeitadas

- **A exceção apenas carregar o enum:** não produz estado durável e reduz o plano.
- **O assembler mutar o record:** mistura domínio e orquestração, contorna o lock/FSM e dificulta
  rollback.
- **Executar contexto como efeito oculto de um agente do grafo:** permite que o grafo comece antes do
  dual gate e duplica decisões.
- **Usar a policy por path no checkout:** quebra a identidade imutável do bundle e o resume.
- **Adiar toda composição para F4.8:** permitiria concluir F4.3–F4.7 com primitivas desconectadas.
- **Corrigir agora os gates 0/0 dentro de F4.3:** mistura tarefas; os negativos são congelados para
  F4.5–F4.7, mas o código permanece fora da allowlist atual.

## Verificação

- falha por PRD ausente ou índice vazio persiste a decisão e deixa o record em
  `BLOCKED_INSUFFICIENT_CONTEXT`;
- policy/snapshot/persistência inválidos deixam o record em `BLOCKED_PREREQUISITE`;
- nenhum backend de nó é chamado antes de contexto suficiente;
- resume usa o envelope original e preserva todas as tentativas por digest;
- grafos sem policy de contexto mantêm os testes promovidos F2;
- F4.4–F4.8 citam esta decisão em seus gates e não podem declarar conclusão apenas por testes de
  componentes isolados.
