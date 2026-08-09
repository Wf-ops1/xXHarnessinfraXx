# Modelo Operacional Agentic — Estado Atual e Arquitetura-Alvo

> **Status: Protótipo / Em desenvolvimento**

Este documento separa o fluxo que o código executa hoje do fluxo que o produto deverá garantir. A
presença de uma classe, estado da FSM ou teste unitário não significa que a integração externa ou o
efeito operacional correspondente já exista.

## Fluxo observado no protótipo

```mermaid
sequenceDiagram
    autonumber
    actor User as Desenvolvedor
    participant CLI as CLI
    participant Engine as RuntimeEngine
    participant Model as Adapter LLM simulado
    participant Verify as VerificationEngine
    participant Promo as PromotionManager
    participant Memory as CodebaseMemoryAdapter
    participant Audit as AuditTrailManager

    User->>CLI: harness run workflow
    CLI->>Engine: run_workflow
    Engine->>Engine: contexto e plano locais
    Engine->>Model: complete
    Model-->>Engine: resposta fabricada
    Engine->>Verify: executar gates configurados
    Verify-->>Engine: resultado real ou lista vazia
    Engine->>Promo: promote(dry_run=true)
    Promo-->>Engine: SHA sintético
    Engine->>Memory: query_ast
    Memory-->>Engine: mock_ast persistido
    Engine->>Audit: eventos e evidence.json
```

O fluxo exercita contratos e persistência local, mas não modifica código por um modelo real, não cria
candidate commit em worktree e não promove por cherry-pick. O estado `COMPLETED` do protótipo não
deve ser interpretado como entrega real da intenção do usuário.

## Fluxo-alvo

```mermaid
sequenceDiagram
    autonumber
    actor User as Desenvolvedor
    participant Engine as Runtime persistido
    participant Worktree as Worktree Git externo
    participant Model as Provider real
    participant Tools as ToolRouter fail-closed
    participant Verify as Gates reais
    participant Approval as Aprovação humana
    participant Git as Promoção Git
    participant Audit as Evidência auditável

    User->>Engine: intenção
    Engine->>Worktree: criar a partir do base SHA
    Engine->>Model: solicitar ação autorizada
    Model->>Tools: argv e paths validados
    Tools->>Worktree: alterar somente dentro do isolamento
    Engine->>Verify: executar gates obrigatórios
    Verify-->>Engine: resultado sem sucesso vazio
    Engine->>Approval: pausar e persistir
    Approval-->>Engine: decisão autenticada
    Engine->>Git: candidate commit e cherry-pick
    Git-->>Audit: SHAs, diff, gates e decisão
```

## Contratos que já possuem base

- empacotamento e ambiente de desenvolvimento reproduzíveis;
- contratos Pydantic, defaults e versionamento de schemas;
- FSM e arquivos locais de contexto, plano, estado e evidência;
- `ExternalWorktreeManager` com `git worktree` real, referência durável e path guard canônico;
- execução de subprocessos de verificação por `argv`, com executável autorizado, cwd confinado,
  ambiente seletivo, timeout da árvore de processos e saída limitada/redigida;
- edição local real por leitura, listagem, busca e patch atômico confinados, além de cliente Serena MCP
  explícito com prova de raiz, capability e mudança;
- factory opt-in para registrar oito tools operacionais sem relaxar a policy compilada ou deny-wins;
- hash chain local para o diário de eventos.

## Lacunas que impedem uso seguro

- providers OpenAI/local fazem chamadas reais quando configurados, mas nenhum backend agentic padrão
  fecha sozinho o fluxo do produto;
- Serena possui cliente MCP explícito e opt-in; Codebase-Memory ainda não oferece memória real;
- `doctor` não mede saúde;
- o worktree Git real ainda não está ligado automaticamente ao lifecycle e ao registry opt-in;
- promoção e rollback não possuem o protocolo Git final;
- terminal, edição local, Git somente leitura e Serena possuem registrations opt-in, mas o lifecycle
  ainda não constrói esse registry nem injeta o worktree provisionado;
- persistência, recovery, budgets, secrets e políticas ainda não controlam todo o caminho crítico.

O plano concreto para fechar essas lacunas está em
[plano_implementacao_harness_operacional.md](plano_implementacao_harness_operacional.md).
