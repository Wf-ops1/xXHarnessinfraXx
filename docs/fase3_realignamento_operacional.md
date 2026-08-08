# Realinhamento operacional da Fase 3

> **Decisão:** DEC-012
> **Estado:** gate de saída certificado no primeiro commit de F3.4; preservado como norma histórica
> **Baseline auditada:** `0e64a88fbe1ca28b8da6a4598a4f4391ba916dd1`
> **Autorizado em:** `2026-08-07T23:48:49-03:00`

## 1. Finalidade

Este documento amarra, em uma única fonte normativa, a correção do desvio operacional ocorrido na
sequência F3.1–F3.3 e os reforços técnicos necessários antes de F3.4. Ele complementa as seções 1.1,
1.2 e a Fase 3 do plano principal; não substitui o dossiê ativo de cada tarefa.

O código já promovido continua sendo evidência válida de implementação e CI. O problema é duplo:

1. F3.2 e F3.3 avançaram sem a pausa humana explícita exigida entre tarefas;
2. a auditoria pós-merge encontrou lacunas de contrato que os testes vigentes não exerciam.

Os dossiês já promovidos permanecem imutáveis. Este documento é a errata explícita e auditável; não
se reescreve silenciosamente autorização, resultado, SHA, PR ou run histórico.

## 2. Estado técnico observado

| ID | Evidência | Impacto se não corrigido |
|---|---|---|
| R3-01 | `runtime/tool_loop.py` transforma resultados em `<tool_loop_transcript>` textual e reinicia o prompt | providers reais podem ignorar, rejeitar ou repetir tool calls; F3.4–F3.8 ficariam sobre continuação não nativa |
| R3-02 | `LLMResponse` aceita `total_tokens` diferente de `prompt_tokens + completion_tokens`; reprodução aceitou `100 + 100` com total `0` | budget pode ser contornado e evidência de custo fica inconsistente |
| R3-03 | `json.loads` aceita `NaN` e chaves duplicadas em argumentos/structured output | contrato JSON deixa de ser interoperável e a falha ocorre tarde |
| R3-04 | `ToolLoopResult` e `NodeExecutionResult` preservam somente o último model call | turnos anteriores e falhas perdem provider, modelo, usage, request ID e response ID |
| R3-05 | eventos de tool são gravados somente depois de o backend retornar | crash após efeito pode deixar o journal sem chamada durável correspondente |
| R3-06 | deny-wins/overlap e `human_approval_required` não são aplicados no ponto de dispatch | uma configuração inválida ou futura capability operacional pode executar fora da decisão compilada |

R3-01–R3-04 pertencem a F3.C1. R3-05–R3-06 pertencem a F3.C2. F3.4 permanece bloqueada até ambas
serem promovidas e auditadas contra as fases posteriores.

## 3. Ordem corretiva obrigatória

```text
F3.C1 — Integridade de modelo e model-turn
  → PR único completamente verde
  → merge commit
  → CI push da main no SHA exato completamente verde
  → sincronizar main
  → PAUSA HUMANA OBRIGATÓRIA

F3.C2 — Execução durável de tools e policy
  → somente após autorização explícita nova
  → PR único completamente verde
  → merge commit
  → CI push da main no SHA exato completamente verde
  → sincronizar main
  → PAUSA HUMANA OBRIGATÓRIA

F3.4 — Path guard
  → somente após auditoria de compatibilidade e autorização explícita nova
```

Uma autorização ampla para “executar a Fase 3” não substitui a autorização posterior de cada tarefa.
`COMPLETED_LOCAL / PROMOTION_PENDING`, merge ou CI verde nunca autorizam avanço automático.

## 4. Contrato da F3.C1 — Integridade de modelo e model-turn

### Resultado obrigatório

- continuação de tools representada por contrato tipado e provider-neutral;
- Responses API com estado manual preserva todos os itens de `response.output`, inclusive reasoning,
  e recebe `function_call_output` no segundo request; estado provider-native permanece só em memória
  e só retorna ao mesmo provider, enquanto fallback usa a representação normalizada;
- Chat Completions recebe mensagem `assistant.tool_calls` e mensagens `role=tool` com
  `tool_call_id` no segundo request;
- nenhum provider real recebe transcript textual como substituto do protocolo nativo;
- usage é inteiro não negativo e `total_tokens == prompt_tokens + completion_tokens`;
- JSON de provider rejeita `NaN`, `Infinity`, `-Infinity` e chaves duplicadas;
- cada model call concluído fica representado, em ordem, no sucesso e nas falhas posteriores;
- journal de node persiste a lista redigida de metadata de todos os model calls e replay valida tanto
  o formato novo quanto eventos históricos de chamada única;
- cancelamento é verificado antes de cada candidato, depois de falha transitória, depois da resposta
  e antes de qualquer fallback, budget ou próximo efeito.

### Fora de escopo

- não alterar dispatch ou durabilidade de efeitos de tool, que pertencem a F3.C2;
- não implementar path guard, terminal, worktree, promoção ou edição de F3.4–F3.8;
- não criar provider novo, dependência, workflow de CI ou backend default;
- não persistir prompt, conteúdo do modelo, argumentos/resultados brutos, headers ou secrets.

## 5. Contrato da F3.C2 — Execução durável de tools e policy

F3.C2 será recongelada em dossiê próprio após a pausa, mas não poderá reduzir estes mínimos:

- `TOOL_CALLED` write-ahead antes do dispatch, usando o mesmo lock e fencing do node;
- outcome de tool somente depois do efeito, com crash tests antes do dispatch, após a chamada, após o
  efeito e antes/depois do outcome;
- chamada aberta ou ambígua bloqueia retomada e nunca é reexecutada automaticamente;
- deny-wins efetivo, overlap allow/deny rejeitado e `human_approval_required` preservado;
- enquanto F5.6 não fornecer aprovação vinculada ao conteúdo, tool que exige aprovação falha fechada
  antes do dispatch;
- budget e cancelamento verificados imediatamente antes de cada dispatch;
- ausência de registrations significa registry operacional vazio; handlers determinísticos ficam em
  testes e capability declarada nunca vira adapter sintético de produção.

## 6. Dependências protegidas

| Consumidor futuro | Garantia fornecida pelo realinhamento | Trabalho que continua pertencendo à fase futura |
|---|---|---|
| F3.4–F3.8 | continuação nativa, usage íntegra, evidência completa e dispatch fail-closed/durável | path guard, terminal, worktree, promoção e edição reais |
| F4 | model/tool turns auditáveis para planejamento, gates e repair | indexação, contexto, plano e verificação reais |
| F5 | pontos de enforcement e falha fechada para budget/policy/aprovação | trust boundary, secrets, budget durável e aprovação vinculada |
| F6 | metadata estruturada e sequência durável para journal/recovery | schema global, evidence manifest, doctor e recovery completo |
| F7 | base observável para cenários E2E e release | matriz E2E, empacotamento e release candidate |

Nenhuma correção local garante antecipadamente que uma fase futura está concluída. O gate de cada
tarefa futura deve reauditar suas dependências e permanecer `BLOCKED` diante de divergência real.

## 7. Modo de operação obrigatório do executor

1. Ler integralmente `AGENTS.md`, `TASK.md`, dossiê ativo, seções 1.1–1.2, Fase 3 e este documento.
2. Confirmar worktree limpa, `main == origin/main` e CI push verde no SHA exato.
3. Trabalhar uma tarefa por vez, em branch `task/<id>-<descrição>`, com um único PR.
4. No primeiro commit do gate, certificar/arquivar a tarefa anterior e criar o novo dossiê completo.
5. Manter o gate `BLOCKED` até problema, evidências, baseline, escopo, aceite, rollback, executor,
   runtime e horário estarem completos; só então marcar `READY` e criar checkpoint.
6. Se surgir arquivo, efeito, dependência ou critério fora do congelado, parar antes da edição,
   documentar a descoberta e recongelar; ampliação material recebe novo checkpoint.
7. Critério falho nunca é removido, ignorado, afrouxado ou substituído para obter verde.
8. Executar focais, regressão completa, Ruff, mypy, compileall, `uv lock --check`,
   `git diff --check`, build/smoke aplicável e auditoria de escopo.
9. Revisar o diff final, registrar evidências no dossiê e publicar somente o único PR da tarefa.
10. Inspecionar explicitamente todos os jobs. Check pendente, ausente, ignorado, neutral ou falho
    proíbe merge; conflito ou branch desatualizada também proíbe merge.
11. Após merge, esperar o CI de `push` em `main`, conferir SHA, matriz e `CI required`, sincronizar a
    `main` local e então parar.
12. A tarefa seguinte exige um novo comando explícito do usuário. O executor não interpreta silêncio,
    plano amplo, CI verde ou “prossiga a fase” anterior como autorização renovada.

## 8. Critério de saída do realinhamento

O realinhamento só termina quando F3.C1 e F3.C2 estiverem `PROMOTED`, seus CIs pós-merge coincidirem
com os respectivos SHAs e uma auditoria no primeiro commit de F3.4 comprovar que não resta achado
blocker/high deste documento. Depois disso, a Fase 3 continua normalmente a partir de F3.4; o gate de
saída original da fase permanece inalterado.

## 9. Saída certificada no gate F3.4

No primeiro commit documental de F3.4 foram observados:

- F3.C1 `PROMOTED`, merge `5616fc5`, CI pós-merge `31240455344` no SHA exato;
- F3.C2 `PROMOTED`, merge `d2502b0`, CI pós-merge `31266993044` no SHA exato;
- `main == origin/main == d2502b0`, worktree limpa antes da branch F3.4;
- 172 testes focados e 6 subtests verdes cobrindo R3-01–R3-06;
- ausência de `tool_loop_transcript` em código de produção, registry operacional vazio e nenhuma
  alteração/habilitação das fronteiras F3.4–F3.8 durante as corretivas.

Não restou achado blocker/high deste documento. A ambiguidade entre F3.4 e F3.6 foi resolvida pela
[DEC-013](decisions/DEC-013-fase3-ordem-operacional.md): F3.4 cria somente o guard parametrizado;
F3.6 cria o worktree real e consumidores posteriores fazem a integração.
