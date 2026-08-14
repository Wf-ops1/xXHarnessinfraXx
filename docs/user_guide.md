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
| `harness status <id>` | Lê a visão canônica do estado persistido e o snapshot agregado de budget | Implementado como leitura local; o saldo F5.4 vem do mesmo journal que governa a execução |
| `harness inspect <id>` | Exibe digests, eventos, aprovação e saldo por execução/nó sem secrets | Implementado como inspeção local; não usa contador paralelo de apresentação |
| `harness approve <id>` | Aprova a pausa de node ou uma solicitação de promoção já criada e ligada ao conteúdo | A CLI não cria candidate/request automaticamente; promoção opt-in usa a API canônica e continua separada |
| `harness resume <id>` | Retoma exclusivamente do bundle canônico persistido | Não aceita perfil/override novo nem relê configuração viva; depende dos mesmos backends explicitamente injetados |
| `harness cancel <id>` | Publica decisão/pedido duráveis, interrompe comando operacional vinculado e reconcilia `CANCELLED` após quiescência | Não remove worktree; a tool/terminal precisa ter sido composta com o controlador da mesma execução |
| `harness cleanup-worktree <id>` | Remove explicitamente o worktree ativo, limpo e no HEAD esperado | Nunca usa force nem apaga branch; worktree sujo ou divergente é recusado |
| `harness verify <execution_id> [--project-id <id>]` | Carrega o `ProvisionedWorktree`, detecta configuração e executa a suíte canônica compilada | F4.5–F4.8 bloqueiam pré-requisito inválido, persistem resultados commit-bound e exigem targeted → full após reparo; worktree/provider ainda precisam existir |
| `harness audit <id>` | Verifica/exporta o diário local | Implementação local; não prova efeitos reais |
| `harness rollback <id>` | Reverte por argv o `promotion_commit_sha` canônico e verifica o novo SHA/parent/worktree | Exige execução `COMPLETED`, raiz/branch/trust exatas e checkout limpo; conflito faz abort e termina `BLOCKED_ROLLBACK`; ainda não reexecuta gates |

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

## Orçamento durável F5.4

A implementação local F5.4 substitui, no lifecycle persistido, o contador process-local por um
ledger derivado do journal canônico. A configuração efetiva aceita limites positivos de prompt,
completion/total, tool calls, duração, tentativas e custo, além de overrides por nó, preços decimais
por `provider:model`/tool e o teto conservador de completion por chamada. Essa projeção é persistida no
bundle; `resume` não relê tetos ou preços vivos.

Depois de egress, policy F5.2, trust boundary F5.3 e cancelamento, cada provider/tool reserva uma
estimativa determinística antes do transporte/handler. Uma negação pré-efeito não é cobrada. Resposta
de modelo confirma prompt/completion/total reais exatamente uma vez; tool despachada confirma
sucesso/falha, duração monotônica e custo conhecido. Sem preço aplicável o custo fica indisponível,
nunca zero; se houver teto monetário, a ausência de preço bloqueia antes do efeito.

Reinício e `resume` reconstruem execução e nós dos eventos `BUDGET_RESERVED`, `BUDGET_COMMITTED`,
`BUDGET_RELEASED` e `BUDGET_EXCEEDED`, reaproveitando evidência histórica anterior. Identidade,
digest de limites, fencing, ordem ou payload divergente falham fechado. Excesso leva a
`FAILED_BUDGET_EXCEEDED`; retomar esse estado não chama provider, tool, nó ou fallback. Os guards
específicos de repair/verificação F4.8 continuam existindo, e o limite mais restritivo prevalece.

Essa capacidade está local e ainda aguarda checkpoint/promoção próprios. Ela não adiciona a
composição automática de providers, tools ou worktree ao CLI.

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
    a projeção F5.2 declara esses eixos explicitamente como abrangentes. Na F5.3 promovida,
uma fronteira externa tipada restringe modo, raiz exata e allowlists de contratos Python, aliases,
nomes de secrets e hooks. Cada registration fornece operação e path reais ao avaliador.

Antes do primeiro efeito, o tool loop valida schema e autoriza o lote inteiro. Uma única negação
bloqueia todas as chamadas do lote. O `ToolRouter` exige a decisão positiva, reavalia-a no mesmo
engine e confere tool/operação/path. `TOOL_CALLED` guarda a decisão e a regra sem argumentos brutos;
o outcome guarda seu digest. O replay aceita journals históricos, mas rejeita evidência nova parcial
ou divergente.

Isso não liga as tools automaticamente ao lifecycle padrão. O caminho executável atual não aceita um
booleano do chamador como prova: policy que exige aprovação bloqueia antes do egress. A F5.6 liga a
decisão humana de **promoção** ao candidate e à evidência verificada; ela não converte
`approval_granted` da policy de tools em autorização humana. A F5.3 e a F5.4 preservam trust e budget
antes de qualquer efeito.

## Secrets e redaction F5.5

A implementação F5.5 está promovida e reconciliada. Valores só são lidos do ambiente depois de um
`TrustEvaluationResult` autorizar o nome e o consumer exatos. A configuração efetiva persiste apenas
o nome em `api_key_env`; não coloque valores em YAML, JSON, prompt, system prompt, argumentos de tool
ou arquivos `.env` do projeto.

| Nome suportado | Consumer exato | Fronteira de injeção |
|---|---|---|
| `OPENAI_API_KEY` | `provider:openai` | header `Authorization` do transporte OpenAI |
| `HARNESS_LOCAL_MODEL_API_KEY` | `provider:local` | header do endpoint local, quando configurado |
| `SERENA_MCP_TOKEN` | `tool:serena` | `secret_headers` ou `secret_environment` da Serena |

Nomes adicionais de provider continuam possíveis somente quando `api_key_env` e o grant declaram o
mesmo nome para `provider:<id>`. O adapter Anthropic permanece fail-closed e não deve ser tratado como
integração funcional. OpenAI/local não consultam mais variáveis de credencial diretamente; sem nome,
boundary e grant, a chamada remota falha antes do transporte.

Na Serena, `headers` e `environment` são públicos. `Authorization`, cookies, API keys e nomes de
ambiente sensíveis em claro são rejeitados; use referências como
`secret_headers={"Authorization": "SERENA_MCP_TOKEN"}` ou
`secret_environment={"SERENA_TOKEN": "SERENA_MCP_TOKEN"}` e forneça ao adapter o mesmo boundary.
Configuração, contexto e representações não enumeram valores crus.

Cada composição do provider/adapter cria um `RedactionContext` imutável somente em memória. Rotação
passa a valer na próxima composição ou reconstrução do resume; instâncias existentes não fazem hot
reload silencioso. Texto exato ou fragmentado por whitespace, headers conhecidos, pares chave/valor
e JSON recursivo são redigidos antes de truncamento e persistência. Provider recebe a credencial
somente no header, nunca no corpo/prompt; terminal e Serena projetam stdout, stderr e resultados MCP
já redigidos antes de retorná-los ao tool loop.

## Aprovação de promoção vinculada ao conteúdo F5.6

A F5.6 promovida separa a pausa de um node `human_approval` da decisão que autoriza promoção. A ordem
canônica da API é:

1. `prepare_candidate(execution_id)` cria e persiste o candidate commit real;
2. `verify(execution_id)` persiste a última suíte completa verde no mesmo SHA;
3. `request_promotion_approval(execution_id, reason=..., expires_at=<UTC>)` cria
   `.harness/state/executions/<id>/approval-request.json`;
4. `approve(execution_id, approver=..., comment=...)` registra a decisão humana;
5. `promote(execution_id)` recompõe e compara todo o subject antes de chamar Git.

O JSON contém execution ID, artifact/plan/diff digests, candidate SHA, resultados e digests dos
gates, razão, validade, status, approver, timestamp e comentário opcional. Em workflows sem planner,
`plan_digest` liga explicitamente a ausência por um marcador canônico; não fica `null`. O arquivo
legado `approval_request.json` e um status `APPROVED` originado apenas por node nunca autorizam
promoção.

Se candidate/diff, plano ou gates divergirem, o lifecycle persiste `INVALIDATED`; se a validade
terminar antes da decisão ou promoção, persiste `EXPIRED`. Tamper, evento/CAS ambíguo ou projeção sem
histórico falham fechados. Nenhum desses casos executa `cherry-pick`. Uma nova tentativa exige nova
solicitação e nova decisão sobre o conteúdo corrente.

## Cancelamento, cleanup e rollback F5.7

O cancelamento usa arquivos de controle duráveis por execução. `cancellation-policy.json` registra a
decisão antes de `cancellation-request.json` e antes do sinal. Isso permite interromper uma tool mesmo
quando o `GraphExecutor` já mantém o lock canônico. O `TerminalAdapter` encerra somente o Windows Job
ou process group criado para aquele comando, reapera o processo e devolve stdout/stderr já limitados
e redigidos. Depois da quiescência, o lifecycle adquire o lock, invalida a aprovação e reconcilia o
journal; só então o estado público vira `CANCELLED`. `resume` recusa primeiro o pedido durável, então
um crash não reabre a aprovação.

Cancelamento nunca remove o worktree. Use `harness cleanup-worktree <id>` como ação separada; ela
exige vínculo da execução, worktree ativo, limpo e no HEAD esperado e delega ao manager não forçado.

`harness rollback <id>` não recebe SHA nem `--promoted`. O lifecycle exige `COMPLETED` e usa somente
o `promotion_commit_sha` persistido. O manager valida raiz, branch, trust, ancestralidade e limpeza,
desabilita hooks/signing e executa `git revert --no-edit <sha>` com `shell=False`. Sucesso requer exit
zero, novo SHA completo, parent igual ao HEAD anterior e worktree limpo. Em conflito, somente
`git revert --abort` é permitido; a execução termina `BLOCKED_ROLLBACK` e não tenta um segundo revert
se o resultado for ambíguo. Hook de produto é injetável/allowlisted e continua default-deny; efeito
destrutivo exige aprovação específica ligada à tentativa de rollback.

Essas APIs estão concluídas localmente, mas não tornam o protótipo seguro para um repositório valioso:
a composição automática de provider/tools/worktree e os gates pós-reversão/evidence recovery
permanecem pendentes.

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
- gates pós-reversão e evidence/recovery abrangente;
- doctor confiável.
- composição automática de worktree, provider e tools no lifecycle padrão; o E2E F4.8 usa
  dependências explicitamente injetadas.

Acompanhe a ordem de implementação no
[plano operacional](plano_implementacao_harness_operacional.md) e o estado executável no
[TASK.md](../TASK.md).
