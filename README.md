# AI Engineering Harness

> **Status atual: Protótipo / Em desenvolvimento**

O AI Engineering Harness é hoje uma base Python instalável para experimentar um harness de engenharia
agentic local-first. O repositório já possui empacotamento reproduzível, compilador único e
determinístico, execução dirigida pelas arestas do artefato, persistência concorrente, FSM por eventos
e retomada canônica com aprovação, cancelamento e retry limitado por contexto real e redigido. A
execução autônoma segura sobre um repositório externo ainda não está pronta: providers, roteamento,
continuação de model-turn e durabilidade/policy do tool loop passaram pelo realinhamento; os
primitivos de worktree Git, terminal por `argv` e edição confinada já são reais. O registry das tools
é opt-in e injetável; sua ligação automática ao lifecycle, promoção, rollback e governança operacional
permanece incompleta.

Não use `harness run`, `harness doctor`, `harness verify` ou `harness rollback` como garantia de segurança em um
repositório valioso. Embora a Fase 2 esteja implementada, as Fases 3–7 ainda não estão concluídas;
execute esses comandos somente em cópias descartáveis.

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
| CLI e scaffold | `--help`, `--version`, `init`, `compile`, `run`, `resume`, `approve`, `cancel`, `status` e `inspect` possuem contratos e testes | Sem backends reais, `run` falha no preflight; doctor, audit, verify e rollback ainda cobrem componentes incompletos | UX estável para CLI e IDE em repositórios externos |
| Compilação de grafos | Um único `GraphCompiler` valida contratos/policies e publica artefato 2.0 determinístico, versionado, íntegro e atômico | Capabilities compiladas ainda são declarativas, sem provar adapter disponível ou autorização runtime | Migrações de schema e expansão segura de workflows após o MVP |
| Runtime/FSM | `GraphExecutor` segue somente arestas compiladas; record/journal usam lock, CAS e fencing; FSM event-sourced e lifecycle retomável suportam aprovação, cancelamento e retry com evidência redigida, limite e resume por digest | Efeito interrompido sem outcome exige intervenção; executores dependem de backends injetados ainda indisponíveis no produto | Efeitos reais e repair loop completo integrados nas Fases 3–6 |
| Providers LLM | OpenAI Responses API e endpoint local Chat Completions executam HTTP real; registry/roteamento vêm da configuração efetiva; continuação nativa, JSON/usage estritos e evidência de todos os model turns foram corrigidos na F3.C1 | Integração live é opt-in; Anthropic falha como não implementado; nenhum backend agentic default torna o protótipo autônomo | Providers adicionais somente após contrato e testes equivalentes |
| Tool loop | Policy compilada, continuação nativa, write-ahead/outcome durável, replay ambíguo fail-closed, deny-wins, budget e cancelamento possuem testes após F3.C2; a factory F3.8 registra oito tools reais quando seus adapters são injetados | O registry opt-in não é construído pelo lifecycle/defaults; aprovação vinculada ao conteúdo ainda não aciona esses efeitos no produto | Integração automática das tools, promoção F3.7 e gates seguintes |
| Serena, índice, contexto e planejamento | Edição confinada e Serena MCP explícito usam efeitos verificados; `PythonAstIndexer` indexa o commit exato; F4.3/F4.4 produzem contexto e plano persistidos; a F4.C1 e sua reconciliação administrativa foram incorporadas pelos PRs #40/#41 | Serena é opt-in e a indexação é Python-only/full rebuild/explícita | Backend Codebase-Memory compatível, memória semântica real e composição dos gates F4.6–F4.8 |
| Verificação e auditoria | F4.5 mantém uma taxonomia única `typecheck/lint/unit_test/build/security_scan`; policy vazia/duplicada/desconhecida e runner `0/0` falham antes de subprocessos; execução usa `argv`, `shell=False`, cwd confinado, ambiente controlado, timeout e saída limitada/redigida | Detecção/comandos efetivos, persistência/guard de conclusão e retry ainda pertencem a F4.6–F4.8; a CLI ainda pode retornar zero quando um comando executado reprova | Matriz integral fail-closed, persistida e com recovery operacional |
| Doctor | Relatório e modelo de probe existem | Todos os seis estágios retornam saudáveis sem testar componentes | Probes reais de configuração, alcance, autenticação e capacidade |
| Worktree, promoção e rollback | `ExternalWorktreeManager` valida repo/branch/cleanliness/SHA, cria `git worktree` externo, persiste referência atômica e fornece `PathGuard` canônico com cleanup explícito | O worktree real ainda não está integrado ao lifecycle/tools; promoção usa dry-run/SHA sintético e rollback é parcial | Candidate commit, cherry-pick e `git revert` reais |
| CI e release | GitHub Actions executa quality/tests/package em Windows e Linux; `main` exige `CI required`, com bloqueio e restauração comprovados | A CI prova o baseline técnico, não as capacidades operacionais ainda simuladas | Distribuição pública e processo de release operacional na F7 |

## Estado do roadmap

- **Fase 0 concluída:** ambiente reproduzível, documentação honesta e CI protegida.
- **Fase 1 concluída:** contrato de grafo, registries seguros, compilador único e artefato 2.0
  determinístico.
- **Fase 2 concluída:** record atômico, storage concorrente, execução por grafo, FSM por eventos,
  retomada vinculada ao artefato/configuração originais e retry que consome erro, tool call,
  stdout/stderr redigidos, gates, diff, orçamento e instrução de correção.
- **Fase 4 iniciada:** F3.1–F3.6, F3.8 e as corretivas F3.C1/F3.C2 aplicáveis foram
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
  comando antes de qualquer efeito. A reconciliação administrativa está aberta no PR #43, no head
  inicial `b304164`; o run inicial `31459427729` começou antes deste registro documental final, que
  exige nova CI integral. F3.7 continua dependente da F4.7.

## Dívidas técnicas críticas

As seguintes implementações são deliberadamente tratadas como dívida técnica, não como capacidades
operacionais:

- [adapters de modelos](src/ai_engineering_harness/models/adapters/) OpenAI/local já usam transporte
  real e Anthropic falha explicitamente; o [roteamento de modelos](src/ai_engineering_harness/models/router.py)
  usa configuração efetiva, egress, fallback transitório e budget; o
  [tool loop](src/ai_engineering_harness/runtime/tool_loop.py) já preserva continuação nativa, todos os
  model turns e eventos de tool duráveis; a factory operacional registra handlers reais somente
  quando adapters explícitos são injetados, mas o lifecycle ainda não a constrói;
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
  e participa do lifecycle com payload, `plan.json` atômico e eventos duráveis. A F4.5 normaliza
  localmente IDs e bloqueia suítes não executáveis; detecção de stack/comando e execução persistida
  permanecem nas F4.6–F4.7;
- [HealthProbe](src/ai_engineering_harness/doctor/probes.py) declara todos os estágios saudáveis sem
  executar probes;
- [PromotionManager](src/ai_engineering_harness/runtime/promotion_manager.py) produz SHA sintético em
  dry-run e possui fallback sintético no caminho live;
- [ExternalWorktreeManager](src/ai_engineering_harness/workspace/git_worktree.py) cria e valida o
  worktree Git real, mas o lifecycle ainda não injeta automaticamente seu guard nas tools;
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
