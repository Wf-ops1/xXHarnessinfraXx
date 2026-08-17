# Matriz de testes F7.2

A F7.2 transforma a lista de cobertura da Fase 7 em uma seleção pytest explícita, verificável e
executável. A fonte canônica é [`tests/f7_2_matrix.json`](../tests/f7_2_matrix.json); o manifesto liga
cada um dos 42 requisitos do plano a funções de teste reais já existentes.

## Comando canônico

No Windows:

```powershell
.\.venv\Scripts\python.exe tests/run_f7_2_matrix.py --collect-only
.\.venv\Scripts\python.exe tests/run_f7_2_matrix.py
```

No Linux ou macOS:

```bash
.venv/bin/python tests/run_f7_2_matrix.py --collect-only
.venv/bin/python tests/run_f7_2_matrix.py
```

O runner usa o mesmo interpretador que o iniciou (`sys.executable -m pytest`), argv sem shell, a
raiz fixa do repositório e um `--basetemp` efêmero externo ao checkout, removido ao terminar. Em um
sandbox que não permita o diretório temporário do sistema, `HARNESS_F7_2_TEMP_PARENT` pode apontar
para um diretório externo gravável; o runner cria e remove somente um filho aleatório próprio. Antes
de criar o subprocesso ele exige JSON estrito, schema e ordem
canônicos, referências relativas sob `tests/unit` ou `tests/e2e`, arquivos existentes, funções
pytest reais no escopo do módulo e node IDs globalmente únicos. Qualquer violação termina com código
não zero.

## Cobertura congelada

| Camada | Requisitos | Node IDs |
|---|---|---:|
| Contracts | validation, compatibility, serialization | 3 |
| Compiler | valid graphs, invalid graphs | 2 |
| Runtime | branches, retry, pause, resume, cancellation | 5 |
| Persistence | atomicity, lock, replay, corruption | 4 |
| Models | errors, timeout, tokens, structured output, tools | 5 |
| Tools | authorization, path guard, timeout, output limit | 4 |
| Git | worktree, commit, divergence, promotion, revert | 5 |
| Verification | pass, fail, missing tool, empty suite | 4 |
| Security | secrets, egress, trust, command injection | 4 |
| Observability | sequence, hash, redaction, export | 4 |
| E2E | ciclo completo em repositório externo | 1 |
| Recovery | crash injection em checkpoints críticos | 5 |
| **Total** | **42 requisitos** | **46 node IDs únicos** |

Recovery usa cinco provas distintas: transição event-sourced, efeito de model/tool, gate de
verificação, promoção Git e knowledge transaction. Por isso a cardinalidade de node IDs é maior que
a de requisitos.

## Relação com a regressão e a CI

A matriz é uma curadoria rastreável, não uma substituição da suíte integral. O aceite local continua
exigindo `pytest tests/unit tests/e2e`, Ruff, mypy, compileall, build e smoke da wheel. A CI continua
executando seu workflow versionado sem depender deste runner; assim, uma prova selecionada verde não
oculta regressões fora da F7.2.

Este artefato comprova somente a matriz prevista na F7.2. Ele não declara cobertura das tarefas
F7.3–F7.5, não altera produto, configuração, dependências ou workflow e não autoriza provider live,
rede ou credenciais.
