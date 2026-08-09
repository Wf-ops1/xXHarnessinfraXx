# Especificação Arquitetural — AI Engineering Harness

> **Status: Arquitetura-alvo / Em desenvolvimento**
> **Revisão documental:** 1.0.0 — não confundir com package ou schema version

## 1. Visão do produto

O produto pretende ser uma infraestrutura local-first instalável por CLI ou IDE. Um repositório
externo deverá receber configuração leve em `.harness/`, enquanto execução, ferramentas, Git,
políticas e evidências permanecerão controlados pelo motor instalado.

No estado atual, essa visão está parcialmente materializada como harness de testes, contratos e
primitivas operacionais reais. O isolamento por worktree, terminal e edição existe de forma injetável,
mas o produto ainda não os compõe automaticamente no lifecycle e não oferece autonomia suficiente
para uso cotidiano sem supervisão.

## 2. Arquitetura-alvo

```mermaid
flowchart TD
    A["Intent e configuração do produto"] --> B["Compilador único e validado"]
    B --> C["Artefato executável versionado"]
    C --> D["Runtime persistido e retomável"]
    D --> E["Provider real + ToolRouter fail-closed"]
    E --> F["Worktree Git externo"]
    F --> G["Gates obrigatórios"]
    G --> H["Aprovação e promoção Git"]
    H --> I["Evidência, observabilidade e recovery"]
```

## 3. Mapeamento atual

| Camada | Base existente | Estado | Limite principal |
|---|---|---|---|
| Package e defaults | `pyproject.toml`, `uv.lock`, `src/ai_engineering_harness/defaults/` | Implementada como base | Distribuição de produto e compatibilidade externa ainda não fechadas |
| Contratos | `src/ai_engineering_harness/contracts/` | Implementada como modelos internos | Evolução/migração compatível dos schemas ainda não está fechada |
| Compilação | `src/ai_engineering_harness/compiler/` com wrapper legado em `compiler/` | Implementada como pipeline canônico | Distribuição e migração externa dos contratos ainda não estão fechadas |
| Runtime | `src/ai_engineering_harness/runtime/` | Implementado como núcleo injetável | Percorre arestas, persiste e retoma; wiring padrão não fornece executores/tools operacionais nem promoção |
| Ferramentas/modelos | `tools/`, `models/`, `indexer/` | Experimental | Edição confinada, terminal, Git somente leitura e Serena MCP possuem registry opt-in; integração automática e memória real ainda faltam |
| Verificação | `verification/` | Experimental | Gates estáticos usam o terminal confinado; fail-closed integral e matriz completa ainda faltam |
| Governança/segurança | `governance/`, `security/` | Experimental | Enforcement não cobre todo side effect |
| Auditoria | `observability/audit.py` | Experimental | Hash chain local não prova efeitos externos nem recovery |
| Workspace Git | `workspace/` | Implementada como primitivo | Cria/valida worktree Git externo e guard canônico; integração com lifecycle/tools ainda falta |

## 4. Separação Harness vs. produto

- **Motor instalado:** código sob `src/ai_engineering_harness/`, contratos, defaults e CLI.
- **Configuração do produto:** `.harness/agents/`, `.harness/graphs/specs/`,
  `.harness/policies/` e `.harness/tools/`.
- **Estado local:** `.harness/state/` e `.harness/artifacts/`.
- **Isolamento disponível como primitivo:** worktree Git externo associado a `execution_id`; uma
  factory opt-in aceita seu guard explicitamente, mas a injeção pelo lifecycle continua pendente.

`harness init` cria/copia a estrutura local, mas isso não torna o repositório governado ou seguro por
si só.

## 5. Invariantes do contrato final

- nenhuma escrita fora do worktree autorizado;
- comandos como `argv: list[str]`, `shell=False`;
- gate obrigatório ausente ou não executado termina em erro;
- adapters indisponíveis falham com erro tipado;
- dry-run não usa semântica de promoção concluída;
- aprovação, orçamento e política controlam side effects;
- secrets são redigidos antes da persistência;
- estado necessário para retomar sobrevive a crash;
- promoção e rollback usam operações Git explícitas com SHAs reais.

Essas invariantes são requisitos do plano. Enquanto qualquer uma não estiver garantida no caminho
crítico, o projeto permanece protótipo.
