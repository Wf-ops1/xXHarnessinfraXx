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
| `harness verify` | Executa gates Python selecionados | Experimental: cobertura e política fail-closed ainda incompletas |
| `harness audit <id>` | Verifica/exporta o diário local | Implementação local; não prova efeitos reais |
| `harness rollback <id>` | Registra compensação e possui caminho Git legado | Não usar em repo valioso; não está ligado ao worktree/terminal tipado nem reexecuta gates |

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

Acompanhe a ordem de implementação no
[plano operacional](plano_implementacao_harness_operacional.md) e o estado executável no
[TASK.md](../TASK.md).
