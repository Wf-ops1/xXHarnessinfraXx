# Guia de Uso do Protótipo — AI Engineering Harness

> **Status: uso de desenvolvimento em ambiente descartável**

O pacote ainda não está publicado como ferramenta operacional nem é seguro para automatizar mudanças
em um repositório valioso. Este guia descreve como inspecionar e testar o protótipo no clone do
projeto.

## Preparar o ambiente

```bash
uv sync --all-extras
uv lock --check
uv run harness --version
uv run harness --help
```

Para validar o baseline:

```bash
uv run python -m pytest
uv run python -m mypy src
uv run python -m ruff check .
uv run python -m compileall -q src compiler tests
uv run python -m build
```

## Comandos e limitações

| Comando | O que faz hoje | Estado/limitação |
|---|---|---|
| `harness --version` | Lê a versão da metadata instalada | Implementado |
| `harness init` | Cria `.harness/` e copia defaults disponíveis | Implementado como scaffold; testar somente em repo descartável |
| `harness doctor` | Renderiza quatro componentes em seis estágios | Simulado: retorna saudável sem conectividade real |
| `harness compile <yaml>` | Compila pelo `GraphCompiler` canônico do pacote | Implementado como contrato interno; estabilidade/migração externa ainda não fechadas |
| `harness index` | Usa `PythonAstIndexer` para reconstruir módulos, classes, funções/métodos e imports dos blobs `.py` do commit Git atual e publica `.harness/state/structural-index/snapshots/<sha>.json` | Implementado para Python por full rebuild; working tree/untracked não entram, erro Git/encoding/sintaxe falha sem snapshot parcial |
| `harness run <workflow>` | Compila/carrega artefato e inicia o lifecycle canônico | Fail-closed: o wiring padrão possui registry de executores vazio e não executa modelos/tools automaticamente |
| `harness status <id>` | Lê a visão canônica do estado persistido | Implementado como leitura local |
| `harness inspect <id>` | Exibe digests, eventos e aprovação sem secrets | Implementado como inspeção local |
| `harness approve <id>` | Persiste decisão ligada à revisão corrente | Exige retomada explícita e ainda não promove por Git |
| `harness resume <id>` | Retoma exclusivamente do bundle canônico persistido | Implementado como contrato; depende dos mesmos backends explicitamente injetados |
| `harness verify <execution_id> [--gate <id> ...]` | Carrega o `ProvisionedWorktree`, detecta configuração e executa gates canônicos selecionados | F4.5/F4.6 bloqueiam seleção ou pré-requisito inválido antes de efeitos; ainda é inseguro como decisão porque reprovação executada pode retornar exit zero e resultados não são persistidos/ligados ao commit |
| `harness audit <id>` | Verifica/exporta o diário local | Implementação local; não prova efeitos reais |
| `harness rollback <id>` | Registra compensação e possui caminho Git legado | Não usar em repo valioso; não está ligado ao worktree/terminal tipado nem reexecuta gates |

## Envelope e gate de contexto F4.3

Os defaults `new-feature`, `bug-fix`, `refactoring` e `migration` declaram a policy compilada
`policies/context_sufficiency.yaml`. Para eles, o envelope exato é
`context_request + graph_input`: `--input-json` deve conter exatamente essas duas chaves,
`context_request`, usada somente pela preparação pré-grafo, e `graph_input`, validada e entregue ao
entrypoint depois de contexto suficiente. Exemplo PowerShell para `new-feature`:

```powershell
$inputJson = '{"context_request":{"requirement_id":"req-1","graph_type":"new_feature","query":"Adicionar logging"},"graph_input":{"requirement_id":"req-1","graph_type":"new_feature","query":"Adicionar logging"}}'
harness run new-feature --input-json $inputJson
```

Antes do comando, o repositório precisa conter o snapshot íntegro do commit atual em
`.harness/state/structural-index/snapshots/<sha>.json` e todos os arquivos do manifesto sob
`.harness/knowledge/artifacts/<artifact_id>.md`. A F4.3 não cria nem atualiza esses pré-requisitos.

O lifecycle persiste o envelope inteiro no bundle, calcula seis dimensões com precisão decimal,
publica somente a projeção sem conteúdo bruto em
`.harness/state/executions/<execution_id>/context.json` e registra `CONTEXT_EVALUATED` apontando para o
relatório por digest. Os resultados são fail-closed:

- contexto suficiente: `CONTEXT_ASSEMBLING → PLANNING`; a implementação local F4.4 exige plano
  durável antes de `PLANNING → EXECUTING`, entregando ao grafo somente `graph_input`;
- manifesto, snapshot vazio, relevância zero ou confiança insuficiente:
  `BLOCKED_INSUFFICIENT_CONTEXT`, sem executar nó;
- policy, snapshot ou persistência inválida: `BLOCKED_PREREQUISITE`, sem fabricar score;
- uma tentativa inicial e duas retomadas são permitidas; nova retomada termina em
  `FAILED_RETRY_EXHAUSTED`.

`harness resume <id>` sempre recarrega o envelope, commit, artefato e policy originais. Não existem
`force_confidence`, override de score ou fallback para policy mutável. A auditoria R6 do PR #36
reproduziu suficiência sem evidência de artefato e com identidade de request divergente; o reparo agora
vincula identidade/digest, manifesto/evidência e path canônico. A F4.3 e sua reconciliação
administrativa #37 foram promovidas, ambas com CI pós-merge verde. A implementação local F4.4 agora:

- valida rota/egress antes de reler artefatos ou construir o prompt;
- exige structured output compatível com `PlanContent` e anexa identidades confiáveis por código;
- vincula targets/critérios à evidência, gates à policy de verificação e tools à policy compilada;
- persiste `PLAN_GENERATION_STARTED`, payload content-addressed, `plan.json` atômico e
  `PLAN_GENERATED` antes do primeiro nó;
- recupera um plano gerado em resume sem segunda chamada; efeito iniciado sem outcome bloqueia em
  `BLOCKED_PREREQUISITE`.

F4.4, F4.C1 e F4.5 foram promovidas. A implementação local F4.6 exige worktree validado, detecta a
stack pela configuração real, resolve toda a suíte em `argv` e falha `ERROR_PREREQUISITE` antes do
primeiro subprocesso se configuração ou ferramenta faltar. Isso não transforma o protótipo em
execução autônoma porque o registry padrão de executores continua vazio e F4.7–F4.8 ainda precisam
persistir/guardar e reparar os gates.

## Teste controlado de `init`

Crie um repositório descartável e execute o binário instalado pelo ambiente do clone. Confirme os
arquivos gerados antes de removê-los. Não aponte o protótipo para um checkout com trabalho não
commitado.

## O que ainda não está disponível

- instalação pública estável por `pipx`, `uv tool` ou extensão de IDE;
- seleção/injeção automática de provider e tools pelo lifecycle padrão;
- Serena live plug-and-play e Codebase-Memory semântica real;
- ligação automática entre worktree Git, guard e registry operacional;
- promoção por candidate commit e cherry-pick;
- execução E2E autônoma que use a retomada persistida com backends operacionais;
- rollback seguro e gates pós-reversão;
- doctor confiável.
- atualização/CI do reparo R2 no PR #44 da F4.6, seguida de persistência/guarda/retry em F4.7–F4.8.

Acompanhe a ordem de implementação no
[plano operacional](plano_implementacao_harness_operacional.md) e o estado executável no
[TASK.md](../TASK.md).
