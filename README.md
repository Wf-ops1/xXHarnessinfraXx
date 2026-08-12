# AI Engineering Harness

> **Status atual: Protótipo / Em desenvolvimento**

O AI Engineering Harness é hoje uma base Python instalável para experimentar um harness de engenharia
agentic local-first. O repositório já possui empacotamento reproduzível, compilador único e
determinístico, execução dirigida pelas arestas do artefato, persistência concorrente, FSM por eventos
e retomada canônica com aprovação, cancelamento e retry limitado por contexto real e redigido. A
execução autônoma segura sobre um repositório externo ainda não está pronta: providers, roteamento,
continuação de model-turn e durabilidade/policy do tool loop passaram pelo realinhamento; os
primitivos de worktree Git, terminal por `argv` e edição confinada já são reais. O registry das tools
é opt-in e injetável; sua ligação automática ao lifecycle, rollback e governança operacional
permanece incompleta. A promoção Git segura F3.7 foi promovida, mas continua disponível somente por
composição opt-in explícita; CLI/defaults ainda não constroem automaticamente essa fronteira.

Não use `harness run`, `harness doctor`, `harness verify` ou `harness rollback` como garantia de segurança em um
repositório valioso. Embora as Fases 0–4 estejam implementadas no escopo planejado, as Fases 5–7
ainda não estão concluídas; execute esses comandos somente em cópias descartáveis.

## Objetivo do produto

A arquitetura-alvo continua sendo:

\[
\text{Harness} =
\text{BMAD} \longrightarrow
\text{Graph Engineering} \longrightarrow
\text{Runtime Agentic} \longrightarrow
\text{Tools/Memory} \longrightarrow
\text{Quality/Ops}
\]

Quando concluído, o pacote deverá permitir instalar uma CLI ou integração de IDE, inicializar um
repositório externo, executar alterações dentro de um worktree isolado, bloquear efeitos não
autorizados, verificar o resultado, exigir aprovação, promover por Git e reverter com evidência
auditável. Isso é a direção do produto, não uma descrição do estado entregue.

## Matriz de capacidade

| Capacidade | Implementada | Experimental | Planejada |
|---|---|---|---|
| Ambiente e pacote | `uv.lock`, build de wheel, metadata e toolchain reproduzível | Bootstrap ainda depende de instalar `uv` | Distribuição e instalação externa suportadas como produto |
| Versionamento | Package version única e schemas graph/artifact/policy separados | Compatibilidade ainda é comparação exata | Migrações compatíveis e política de evolução |
| Configuração e governança | A F5.1 promovida resolve seis níveis por `importlib.resources`; a F5.2 local unifica policy default-deny e evidência durável nos oito eixos | Publicação F5.2, secrets injetáveis, budgets duráveis e trust boundary integrado pertencem às tarefas seguintes | Configuração e governança operacionais completas junto da conclusão da Fase 5 |
| CLI e scaffold | `--help`, `--version`, `init`, `compile`, `run`, `resume`, `approve`, `cancel`, `status` e `inspect` possuem contratos e testes; `run` transporta `--profile` e `--config-json` ao resolvedor canônico | Sem backends reais, `run` falha no preflight; doctor, audit, verify e rollback ainda cobrem componentes incompletos | UX estável para CLI e IDE em repositórios externos |
| Compilação de grafos | Um único `GraphCompiler` valida contratos/policies e publica artefato 2.0 determinístico, versionado, íntegro e atômico | Capabilities compiladas ainda são declarativas, sem provar adapter disponível ou autorização runtime | Migrações de schema e expansão segura de workflows após o MVP |
| Runtime/FSM | `GraphExecutor` segue somente arestas compiladas; record/journal usam lock, CAS e fencing; FSM event-sourced e lifecycle retomável suportam aprovação, cancelamento e retry com evidência redigida, limites duráveis e resume por digest. A F4.8 promovida adiciona o reparo orientado pela suíte canônica | Efeito iniciado sem outcome exige intervenção; executores e worktree ainda dependem de backends/providers injetados | Integração automática dos efeitos reais no lifecycle padrão nas Fases 3–6 |
| Providers LLM | OpenAI Responses API e endpoint local Chat Completions executam HTTP real; registry/roteamento vêm da configuração efetiva; continuação nativa, JSON/usage estritos e evidência de todos os model turns foram corrigidos na F3.C1 | Integração live é opt-in; Anthropic falha como não implementado; nenhum backend agentic default torna o protótipo autônomo | Providers adicionais somente após contrato e testes equivalentes |
| Tool loop | A F5.2 local unifica a autorização em um engine tipado default-deny por role, node, workflow, trust mode, tool, operação, path e aprovação; o lote é pré-autorizado e a regra aplicada precede o efeito no journal. A factory F3.8 registra oito tools reais quando seus adapters são injetados | O registry opt-in não é construído pelo lifecycle/defaults; trust boundary operacional F5.3 e aprovação vinculada ao conteúdo F5.6 ainda não acionam esses efeitos no produto | Integração automática das tools e gates seguintes |
| Serena, índice, contexto e planejamento | Edição confinada e Serena MCP explícito usam efeitos verificados; `PythonAstIndexer` indexa o commit exato; F4.3/F4.4 produzem contexto e plano persistidos; a F4.C1 e sua reconciliação administrativa foram incorporadas pelos PRs #40/#41 | Serena é opt-in e a indexação é Python-only/full rebuild/explícita | Backend Codebase-Memory compatível e memória semântica real |
| Verificação e auditoria | F4.5 mantém a taxonomia única `typecheck/lint/unit_test/build/security_scan`; policy vazia/duplicada/desconhecida e runner `0/0` falham antes de subprocessos. A F4.6 promovida resolve a suíte no `ProvisionedWorktree`; a F4.7 promovida persiste resultados commit-bound e guarda `COMPLETED`. A F4.8 promovida consome somente essa reprovação, agenda o corretor compilado e exige targeted → full com limites de nó, execução, tokens, custo e tempo | O E2E F4.8 injeta backend e provider de worktree explicitamente, sem alegar composição automática do produto | Matriz integral fail-closed com repair/recovery integrada ao lifecycle padrão |
| Doctor | Relatório e modelo de probe existem | Todos os seis estágios retornam saudáveis sem testar componentes | Probes reais de configuração, alcance, autenticação e capacidade |
| Worktree, promoção e rollback | `ExternalWorktreeManager` cria candidate commit real e singular no worktree externo; a composição opt-in F3.7 persiste candidate/promotion SHA, exige aprovação + full suite no mesmo commit e promove somente por `git cherry-pick` com recovery fail-closed | Worktree/tools/promoção não são construídos automaticamente por CLI/defaults; o contrato de aprovação ainda não é vinculado ao diff e rollback permanece parcial | Composição operacional padrão e `git revert` real |
| CI e release | GitHub Actions executa quality/tests/package em Windows e Linux; `main` exige `CI required`, com bloqueio e restauração comprovados | A CI prova o baseline técnico, não as capacidades operacionais ainda simuladas | Distribuição pública e processo de release operacional na F7 |

## Estado do roadmap

- **Fase 0 concluída:** ambiente reproduzível, documentação honesta e CI protegida.
- **Fase 1 concluída:** contrato de grafo, registries seguros, compilador único e artefato 2.0
  determinístico.
- **Fase 2 concluída:** record atômico, storage concorrente, execução por grafo, FSM por eventos,
  retomada vinculada ao artefato/configuração originais e retry que consome erro, tool call,
  stdout/stderr redigidos, gates, diff, orçamento e instrução de correção.
- **Fases 3 e 4 concluídas no escopo planejado:** F3.1–F3.8, F4.1–F4.8 e as corretivas aplicáveis foram
  promovidas. A F3.8 entrou em `main` pelo PR #29 no merge `e6b5b84`, com CI pós-merge `31295594376`
  verde; a reconciliação administrativa foi incorporada pelo PR #30 no merge `c2aa89b`, e a CI
  pós-merge `31316853244` concluiu 11/11 checks verdes. A correção transversal do PR #31 foi
  incorporada no merge `e4292ca`, com CI pós-merge `31319202731` também 11/11 verde. A F4.1 foi
  promovida pelo PR #32 no merge `12ce3b7`, e a CI pós-merge `31323952381` concluiu 11/11 checks
  verdes; sua reconciliação administrativa entrou em `main` pelo PR #33 no merge `571a8eb`, com CI
  pós-merge `31329231458` também 11/11 verde. A F4.2 foi promovida pelo PR #34 no merge `212a9bf`,
  com CI pós-merge `31345231098` também 11/11 verde; sua reconciliação administrativa foi incorporada
  pelo PR #35 no merge `3705693`, e o run pós-merge `31346860397` concluiu 11/11 checks verdes. A F4.3
  preservou os gates R1–R6, corrigiu os falsos sucessos de evidência/identidade e passou na regressão
  local de 679 testes. O PR #36 encerrou no head `84eda1c` com 11/11 checks no run `31414853048` e foi
  incorporado pelo merge `fa31ef8`; a CI de `push` `31419214233` também concluiu 11/11 checks verdes.
  A reconciliação administrativa F4.3 fechou no head `a7f7053` com 11/11 checks no run
  `31430933615`, foi incorporada pelo PR #37 no merge `5c8408d` e a CI pós-merge `31433785637`
  também concluiu 11/11. A F4.4 substituiu o plano genérico por contrato/structured output, evidência
  por digest e persistência integrada ao lifecycle. O PR #38 encerrou no head `fbdb6ee` com 11/11
  checks no run `31442203348`, foi incorporado pelo merge `93ce4ce` e a CI de `push` `31445624269`
  também concluiu 11/11. Sua reconciliação administrativa na branch `docs/promote-f4.4` foi incorporada
  pelo PR #39 no merge `94641d2`; a CI pós-merge `31447628152` concluiu 11/11. Evidência negativa
  posterior reproduziu overwrite entre snapshots concorrentes divergentes do mesmo SHA e levou ao
  estado `POST_PROMOTION_BLOCKED`. A corretiva F4.C1 usa claim exclusivo, concluiu a regressão local
  com `702 passed, 2 skipped, 6 subtests passed` e recebeu 11/11 checks no head `65c5433` pelo run
  `31453116947`. O PR #40 foi incorporado pelo merge `3905d02`, cuja CI de `push` `31453662008`
  também concluiu 11/11; a correção está promovida e o bloqueio técnico foi encerrado. A reconciliação
  administrativa PR #41 foi incorporada pelo merge `362407f`, e a CI de `push` `31455148050`
  concluiu 11/11 checks verdes no SHA exato. A F4.5 foi promovida pelo PR #42: o head final `9e8dfe8`
  recebeu 11/11 checks no run `31457935429`, e o merge `4ae0de7` recebeu 11/11 na CI de `push`
  `31458482033`. A tarefa
  substitui `tests` por
  `unit_test`, centraliza os cinco IDs oficiais e bloqueia seleção vazia/desconhecida/duplicada ou sem
  comando antes de qualquer efeito. A reconciliação administrativa PR #43 foi incorporada pelo merge
  `46b7070`, e a CI de `push` `31459891130` concluiu 11/11 checks verdes. A F4.6 abriu o PR #44 no
  head `f258541`, mas as CIs `31463009231` e `31463962634` reabriram o gate: os jobs Tests Ubuntu
  3.11/3.14 perderam o venv e falharam sem `pytest`. O R3 `167dbe5` passou na recertificação local de
  `738 passed, 5 skipped, 6 subtests passed`, foi publicado no head final `00e8357` e recebeu 11/11
  checks no run `31505324814`, inclusive as provas Ubuntu. O PR #44 foi incorporado pelo merge
  `a4fd1da`, cuja CI de `push` `31510277593` também concluiu 11/11 checks verdes. A reconciliação
  administrativa PR #45 recebeu 11/11 no head final `09ced2f` pelo run `31512605530`, foi incorporada
  no merge `b578515` e recebeu 11/11 na CI de `push` `31513097203`. A F4.7 foi concluída localmente
  no commit de produto `bbc2d93`, com `751 passed, 5 skipped, 6 subtests passed`, qualidade e wheel
  isolada verdes. O PR #46 passou 11/11 no head `0757e26` pelo run `31528005230` e foi incorporado em
  `f7aa43a`; a CI pós-merge `31528955883` falhou somente no E2E concorrente Windows 3.11 e reabriu a
  promoção como `POST_PROMOTION_BLOCKED`. O R1 test-only em `2841346a` passou a corrida `20/20`, a
  regressão de `751 passed, 5 skipped, 6 subtests passed`, qualidade, build e smoke isolado. O PR
  corretivo #47 encerrou no head `b79e14d2` com 11/11 no run `31533353223`, foi incorporado no merge
  `4aa701a` e recebeu 11/11 na CI pós-merge `31534918672`. A reconciliação administrativa F4.7 foi
  incorporada pelo PR #48 no merge `d4e34c7`, cuja CI pós-merge `31541047111` também concluiu 11/11.
  A F4.8 foi promovida pelo PR #49: o produto `8e5e11d` passou na regressão final com `758 passed,
  5 skipped`, qualidade, build e smoke externo da wheel verdes; o head final `f9c8c2d` recebeu 11/11
  checks no run `31550975708`, foi incorporado pelo merge `72f89e3` e recebeu 11/11 na CI pós-merge
  `31551685950`. A reconciliação administrativa encerrou no head `a15b918`, passou 11/11 no run
  `31554671587`, foi incorporada pelo PR #50 no merge `9f75e35` e recebeu 11/11 na CI pós-merge
  `31557794240`. Nenhuma tag remota F4.8 existe. A F3.7 foi promovida pelo PR #51 após duas correções
  test-only: o head final `40f81375` recebeu 11/11 checks no run `31568577459`, foi incorporado pelo
  merge `10d75408` e recebeu 11/11 na CI pós-merge `31568908128`. A recertificação integral R2 passou
  `774 passed, 5 skipped, 6 subtests passed`, além de mypy, Ruff, compileall, build e smoke externo da
  wheel. A reconciliação administrativa foi incorporada pela PR #52 no merge `846c59e`; o workflow
  `CI` `31616226652` passou nesse SHA exato. A composição permanece opt-in e nenhuma tag remota F3.7
  existe.
- **Fase 5 ativa:** a F5.1 foi promovida pelo [PR #53](https://github.com/Wf-ops1/Harnessinfra/pull/53).
  O head final `f42af27` recebeu 11/11 checks no run `31629604755`, foi incorporado pelo merge
  `c46910e` e recebeu 11/11 na CI de `push` pós-merge `31630446370`. A certificação local passou
  `792 passed, 5 skipped, 6 subtests passed`, qualidade, build e smoke externo da wheel. A
  reconciliação administrativa [PR #54](https://github.com/Wf-ops1/Harnessinfra/pull/54) foi
  incorporada pelo merge `fe95a91`; a CI de `push` `31633748837` passou 11/11 nesse SHA exato. A
  F5.2 está `COMPLETED_LOCAL / PROMOTION_PENDING` no produto `ac665b9`: a regressão passou
  `811 passed, 5 skipped, 6 subtests passed`, além de qualidade, build limpo e smoke isolado da wheel.
  Push, PR, merge, tags remotas, remoção de refs e início da F5.3 não estão autorizados.

## Dívidas técnicas críticas

As seguintes implementações são deliberadamente tratadas como dívida técnica, não como capacidades
operacionais:

- [adapters de modelos](src/ai_engineering_harness/models/adapters/) OpenAI/local já usam transporte
  real e Anthropic falha explicitamente; o [roteamento de modelos](src/ai_engineering_harness/models/router.py)
  usa configuração efetiva, egress, fallback transitório e budget; o
  [tool loop](src/ai_engineering_harness/runtime/tool_loop.py) já preserva continuação nativa, todos os
  model turns e eventos de tool duráveis. A F5.2 remove os verificadores duplicados: o engine único
  aplica deny-wins/default-deny aos oito eixos do contexto, o router revalida decisão/target e o
  journal liga regra e digest antes/depois do efeito. A factory operacional registra handlers reais
  somente quando adapters explícitos são injetados, mas o lifecycle ainda não a constrói;
- [SerenaAdapter](src/ai_engineering_harness/tools/adapters/serena.py) abre transporte MCP stdio ou
  Streamable HTTP configurado, comprova capability/raiz e valida a mudança real; instalação,
  configuração e injeção live continuam externas e opt-in;
- [PythonAstIndexer](src/ai_engineering_harness/indexer/python_ast_indexer.py) lê somente blobs Python
  regulares do commit Git resolvido, produz símbolos AST reais e publica pelo contrato íntegro F4.1;
  `harness index` aciona esse rebuild explicitamente, enquanto `CodebaseMemoryAdapter` permanece
  read-only e falha sem snapshot — o lifecycle ainda não compõe a indexação automaticamente;
- [ContextAssembler](src/ai_engineering_harness/runtime/context_assembler.py) calcula as seis dimensões
  `Decimal`, aplica manifesto + threshold, persiste `context.json` sem conteúdo bruto e é chamado por
  `ExecutionLifecycleService` em start/resume para policies compiladas; a correção de tipo R5 e as
  invariantes fail-closed R6 foram recertificadas e promovidas. A F4.4 também foi promovida: o planner
  usa structured output roteado, relê evidência por digest, limita gates/tools às policies compiladas
  e participa do lifecycle com payload, `plan.json` atômico e eventos duráveis. A F4.5 normaliza IDs
  e bloqueia suítes não executáveis; a F4.6 promovida detecta stack/configuração, resolve a suíte no
  worktree e preserva no terminal o launcher ativo selecionado por `sys.prefix`; a F4.7 promovida
  persiste cada outcome e impede `COMPLETED` sem suíte obrigatória aprovada. O R1 concorrente restaurou
  a CI no PR #47 e no merge `4aa701a`; a F4.8 promovida liga essa reprovação ao `on_failure` compilado,
  persiste orçamento/deadline/contexto e exige targeted seguido da suíte completa, mas não integra
  automaticamente worktree/provider/tools ao lifecycle padrão;
- [HealthProbe](src/ai_engineering_harness/doctor/probes.py) declara todos os estágios saudáveis sem
  executar probes;
- [PromotionManager](src/ai_engineering_harness/runtime/promotion_manager.py) cria e promove SHAs Git
  reais com recovery exato; sua composição é opt-in e ainda não é construída pelo CLI/defaults;
- [ExternalWorktreeManager](src/ai_engineering_harness/workspace/git_worktree.py) cria, valida e
  publica candidate real, mas o lifecycle ainda não injeta automaticamente seu guard nas tools;
- [TerminalAdapter](src/ai_engineering_harness/tools/adapters/terminal.py) executa somente `argv`
  autorizado, com `shell=False`, cwd confinado, ambiente seletivo, timeout da árvore de processos e
  saída limitada/redigida; seus handlers são registrados apenas pela factory opt-in e ainda não são
  ligados ao lifecycle como tool agentic padrão.

## Ambiente de desenvolvimento

Pré-requisitos:

- Python 3.11, 3.12, 3.13 ou 3.14;
- `uv`;
- Git.

Após clonar:

```bash
uv sync --all-extras
uv lock --check
uv run python -m pytest
uv run python -m mypy src
uv run python -m ruff check .
uv run python -m compileall -q src compiler tests
uv run python -m build
uv run python tests/ci/smoke_wheel.py
```

Para inspecionar a superfície da CLI sem executar o runtime:

```bash
uv run harness --version
uv run harness --help
```

`harness init` escreve uma pasta `.harness/` no diretório atual. Enquanto o produto estiver em
desenvolvimento, teste o scaffold apenas em um repositório descartável.

## Contrato de versionamento

A versão autoral do pacote fica em `pyproject.toml`. Em runtime,
`ai_engineering_harness.__version__` e `harness --version` leem a metadata instalada.
`graph_schema_version`, `artifact_schema_version` e `policy_schema_version` evoluem de forma
independente; `definition_version` identifica apenas a revisão de uma definição.

## Fonte de verdade

- [TASK.md](TASK.md): painel de execução, evidências, gates e próxima ação;
- [Plano operacional](docs/plano_implementacao_harness_operacional.md): implementação necessária até
  o MVP operacional;
- [Modelo operacional](docs/agentic_operating_model.md): fluxo atual versus fluxo-alvo;
- [Auditoria do ciclo](docs/agentic_lifecycle_audit.md): estado concreto de cada etapa;
- [Especificação arquitetural](docs/harness_architecture_spec.md): arquitetura-alvo e lacunas;
- [Guia do usuário](docs/user_guide.md): comandos seguros e limitações atuais;
- [Walkthrough](docs/walkthrough.md): estrutura real e fluxo observado;
- [Auditoria técnica](docs/walkthrough_audit.md): pendências comprovadas.
