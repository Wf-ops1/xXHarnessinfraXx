# Relatório de Auditoria de Estado — AI Engineering Harness

> **Data da revisão:** 4 de agosto de 2026
> **Status: Protótipo / Em desenvolvimento**
> **Fonte de evidência:** código, testes e Git local; sem inferir capacidade por nome de classe
> **Natureza:** snapshot histórico da F0.5; não representa o estado corrente após as Fases 1–3

Os achados abaixo registram o baseline observado em 4 de agosto e são preservados para auditoria. Não
devem ser usados como painel atual: providers OpenAI/local, worktree Git, terminal por `argv`, edição
confinada e Serena MCP explícito foram implementados posteriormente como primitivas testadas. A
integração automática dessas primitivas ao lifecycle, promoção, memória, doctor e recovery continua
incompleta. Para estado corrente, consulte [`TASK.md`](../TASK.md), o
[`README.md`](../README.md) e a [auditoria do ciclo](agentic_lifecycle_audit.md).

## Resumo executivo

A revisão F0.5 concluiu que o repositório é uma base de harness com boa quantidade de estrutura
interna, mas ainda não é a infraestrutura segura e instalável descrita como objetivo do produto.
Documentos anteriores misturavam arquitetura desejada com comportamento entregue e usavam contagens
de testes antigas como prova de efeitos que os testes não exercitavam.

O baseline F0.4 foi comprovado com 65 testes e 6 subtests, além de empacotamento, versionamento,
lint, tipos e build validados anteriormente. Essa evidência sustenta a base de desenvolvimento; não
sustenta claims de providers, MCP, worktree, promoção ou rollback reais.

## Achados comprovados no checkpoint F0.5

| ID | Achado | Evidência no código | Consequência |
|---|---|---|---|
| DOC-001 | Providers não consultam modelos | [models/adapters/](../src/ai_engineering_harness/models/adapters/) constroem `LLMResponse` fixa | O runtime não executa raciocínio real |
| DOC-002 | Serena não é MCP | [serena.py](../src/ai_engineering_harness/tools/adapters/serena.py) cria/toca arquivo e retorna `True` | “Edição semântica” não foi implementada |
| DOC-003 | Índice AST é simulado | [codebase_memory_adapter.py](../src/ai_engineering_harness/indexer/codebase_memory_adapter.py) usa `mock_ast` | Reindexação não representa a codebase |
| DOC-004 | Doctor sempre aprova | [probes.py](../src/ai_engineering_harness/doctor/probes.py) constrói todos os estágios como OK | Saída do doctor não é diagnóstico |
| DOC-005 | Promoção é sintética | [engine.py](../src/ai_engineering_harness/runtime/engine.py) força `dry_run=True`; [promotion_manager.py](../src/ai_engineering_harness/runtime/promotion_manager.py) cria SHA textual | `COMPLETED` pode existir sem commit entregue |
| DOC-006 | Worktree não é Git | [git_worktree.py](../src/ai_engineering_harness/workspace/git_worktree.py) usa somente `mkdir` e JSON | Não há isolamento do checkout original |
| DOC-007 | Terminal viola contrato final | [terminal.py](../src/ai_engineering_harness/tools/adapters/terminal.py) aceita string e usa `shell=True` | Argumentos e quoting não são fail-closed |
| DOC-008 | Documentação não era portátil | Nove links dependiam do caminho local de uma máquina | Links quebravam após clone em outro diretório |
| DOC-009 | Árvores documentais estavam obsoletas | Referências a `contracts/`, `policies/`, `graphs/specs/` e `observability/log_integrity.py` não resolviam | A estrutura descrita não correspondia ao repo |

## Capacidades que possuem evidência

- pacote Python instalável em ambiente de desenvolvimento e wheel testada externamente na F0.4;
- uma fonte de package version e namespaces separados para schemas;
- contratos Pydantic, defaults, FSM e artefatos locais;
- execução real de alguns subprocessos de verificação;
- diário local encadeado por SHA-256;
- suíte automatizada que cobre contratos internos do protótipo.

## O que falta para chamar de infraestrutura operacional

1. compilador único e artefato canônico;
2. runtime dirigido pelo grafo, persistido e retomável;
3. providers e ferramentas reais com erro tipado;
4. escrita confinada a worktree Git real;
5. gates obrigatórios sem sucesso vazio;
6. aprovação retomável, candidate commit e promoção explícita;
7. segurança, budgets, secrets e políticas no caminho crítico;
8. doctor e recovery confiáveis;
9. E2E em repositório externo, instalação limpa e processo de release.

O detalhamento e os critérios de aceite estão no
[plano de implementação](plano_implementacao_harness_operacional.md).
