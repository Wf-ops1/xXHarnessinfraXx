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
| `harness run <workflow> [--profile <nome>] [--config-json <objeto>]` | Compila/carrega artefato, resolve a configuração tipada e inicia o lifecycle canônico | Fail-closed: configuração inválida não cria execução; o wiring padrão possui registry de executores vazio e não executa modelos/tools automaticamente |
| `harness status <id>` | Lê a visão canônica do estado persistido | Implementado como leitura local |
| `harness inspect <id>` | Exibe digests, eventos e aprovação sem secrets | Implementado como inspeção local |
| `harness approve <id>` | Persiste decisão ligada à revisão corrente | Exige retomada explícita e ainda não promove por Git |
| `harness resume <id>` | Retoma exclusivamente do bundle canônico persistido | Não aceita perfil/override novo nem relê configuração viva; depende dos mesmos backends explicitamente injetados |
| `harness verify <execution_id> [--project-id <id>]` | Carrega o `ProvisionedWorktree`, detecta configuração e executa a suíte canônica compilada | F4.5–F4.8 bloqueiam pré-requisito inválido, persistem resultados commit-bound e exigem targeted → full após reparo; worktree/provider ainda precisam existir |
| `harness audit <id>` | Verifica/exporta o diário local | Implementação local; não prova efeitos reais |
| `harness rollback <id>` | Registra compensação e possui caminho Git legado | Não usar em repo valioso; não está ligado ao worktree/terminal tipado nem reexecuta gates |

## Configuração efetiva F5.1

No início de `run`, o único `ConfigResolver` aplica seis níveis, da menor para a maior prioridade:

1. `defaults/profiles/default.yaml` do pacote instalado, lido por `importlib.resources`;
2. perfil empacotado ou `.harness/profiles/<nome>.yaml` selecionado por `--profile`;
3. `.harness/project.yaml`, preservado sob a chave `project`;
4. `.harness/bmad/custom/*.toml` do time, em ordem de nome;
5. `.harness/bmad/custom/*.user.toml` pessoais, em ordem de nome;
6. o objeto de `--config-json`.

A configuração completa passa por modelos Pydantic estritos antes da criação do bundle ou record.
Chave raiz desconhecida, tipo inválido, perfil ausente/traversal, YAML/TOML malformado, rota não
configurada ou provider fora de egress falham sem estado parcial. A configuração persistida em
`configuration.json` é a projeção canônica redigida; `api_key_env` guarda apenas o nome da variável,
nunca seu valor. O `configuration_digest` do bundle e do record refere-se exatamente a essa projeção.

Exemplo:

```powershell
$configJson = '{"context_sufficiency_threshold":0.85,"models":{"routing":{"primary_provider":"local","fallback_providers":[]}}}'
$inputJson = '{"context_request":{"requirement_id":"req-1","graph_type":"new_feature","query":"Adicionar logging"},"graph_input":{"requirement_id":"req-1","graph_type":"new_feature","query":"Adicionar logging"}}'
harness run new-feature --profile default --config-json $configJson --input-json $inputJson
```

`resume` valida novamente a projeção persistida e seu digest, mas não relê profile, manifesto ou
overrides vivos. Portanto, alterar configuração no disco nunca muda silenciosamente uma execução em
andamento; é necessário iniciar uma nova execução.

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

F4.4, F4.C1, F4.5, F4.6, F4.7 e F4.8 foram promovidas. A F4.6 exige worktree validado, detecta a stack pela
configuração real, resolve toda a suíte em `argv` e falha `ERROR_PREREQUISITE` antes do primeiro
subprocesso se configuração ou ferramenta faltar. A F4.7 persiste os resultados commit-bound e guarda
`COMPLETED`. A F4.8 promovida transforma somente essa reprovação canônica em contexto para
o `on_failure` compilado, executa os gates afetados e depois a suíte integral, com limites duráveis de
nó, execução, tokens, custo e tempo. Isso ainda não torna o protótipo autônomo: o registry padrão de
executores continua vazio e worktree/provider são injetados.

## Autorização de tools F5.2

A autorização runtime usa um único `PolicyEngine`. Cada solicitação é completa e tipada: `role`,
`node_id`, workflow, trust mode, tool, operação, path relativo opcional e estado de aprovação.
Regras `deny` prevalecem, a identidade aplicada é determinística e ausência de regra resulta em
`default-deny`.

A policy compilada continua sendo a fonte do allow/deny por role e node. No runtime, ela é projetada
para workflow/role/node exatos. Como o schema atual ainda não restringe operação, path ou trust mode,
a projeção F5.2 declara esses eixos explicitamente como abrangentes. Na implementação local F5.3,
uma fronteira externa tipada restringe modo, raiz exata e allowlists de contratos Python, aliases,
nomes de secrets e hooks. Cada registration fornece operação e path reais ao avaliador.

Antes do primeiro efeito, o tool loop valida schema e autoriza o lote inteiro. Uma única negação
bloqueia todas as chamadas do lote. O `ToolRouter` exige a decisão positiva, reavalia-a no mesmo
engine e confere tool/operação/path. `TOOL_CALLED` guarda a decisão e a regra sem argumentos brutos;
o outcome guarda seu digest. O replay aceita journals históricos, mas rejeita evidência nova parcial
ou divergente.

Isso não liga as tools automaticamente ao lifecycle padrão. O caminho executável atual não aceita um
booleano do chamador como prova: policy que exige aprovação bloqueia antes do egress. Vincular uma
aprovação real a conteúdo/diff permanece reservado à F5.6. A F5.3 está certificada localmente e
continua pendente de promoção própria.

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
- composição automática de worktree, provider e tools no lifecycle padrão; o E2E F4.8 usa
  dependências explicitamente injetadas.

Acompanhe a ordem de implementação no
[plano operacional](plano_implementacao_harness_operacional.md) e o estado executável no
[TASK.md](../TASK.md).
