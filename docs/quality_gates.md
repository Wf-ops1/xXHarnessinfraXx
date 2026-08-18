# Quality gates

Este projeto trata a CI como uma composição fail-closed de quatro jobs obrigatórios: `quality`,
`tests`, `package` e `security-coverage`. O agregador estável `CI required` só passa quando todos os
quatro terminam com sucesso; falha, cancelamento ou skip de qualquer job bloqueia o merge.

## Reprodução local

Sincronize exatamente o ambiente versionado antes dos gates:

```bash
uv lock --check
uv sync --all-extras --locked
```

Execute os gates de qualidade, regressão e pacote:

```bash
uv run python -m compileall -q src compiler tests
uv run python -m ruff check .
uv run python -m mypy --strict src
uv run python -m pytest tests/unit -q
uv run python -m pytest tests/e2e -q
uv run python -m build
uv run python tests/ci/smoke_wheel.py
```

Para reproduzir o job dedicado de segurança e cobertura:

```bash
uv run python -m pytest tests/unit tests/e2e -q --cov=ai_engineering_harness --cov-branch --cov-report=json:coverage.json
uv run python tests/ci/check_f7_3_coverage.py coverage.json
uv run python tests/ci/check_f7_3_security.py secrets
uv run python tests/ci/check_f7_3_security.py dependencies
```

`coverage.json`, relatórios do auditor e diretórios temporários são evidência efêmera e não devem ser
versionados. Em ambiente confinado, `LOCALAPPDATA`, `TEMP` e `TMP` podem ser apontados para um
diretório externo gravável; isso não altera os critérios.

## Contrato de cobertura

[`tests/ci/f7_3_quality_gates.json`](../tests/ci/f7_3_quality_gates.json) é o manifesto estrito. Ele
fixa seis arquivos do core, o mínimo agregado de 80% para statements e branches e 23 kernels de
decisão. O checker valida o JSON do coverage.py, os paths, os selectors pela AST e exige zero arco
ausente cuja origem pertença a um kernel. Um arquivo não medido, função removida/renomeada, relatório
malformado ou threshold reduzido falha fechado.

Cobertura é uma condição adicional: ela não substitui os testes comportamentais nem autoriza remover,
pular ou marcar como `xfail` um cenário que exponha defeito real.

## Secrets

O gate enumera com Git todos os arquivos rastreados e não rastreados que não estejam ignorados e os
envia ao `detect-secrets-hook` sem shell. [`.secrets.baseline`](../.secrets.baseline) contém somente
fixtures deliberadas revisadas; cada finding deve declarar `"is_secret": false`, apontar para arquivo
existente e permanecer confinado ao repositório. Um finding novo, baseline inválido ou scanner
indisponível bloqueia o gate.

Uma ocorrência só pode entrar no baseline após inspeção humana comprovar que é dado sintético ou
evidência pública não secreta. Credenciais reais nunca devem ser registradas ou suprimidas.

## Dependências

O gate executa `pip-audit` sobre o ambiente local previamente sincronizado pelo `uv.lock`. O wrapper
compara o relatório JSON à metadata de todas as distribuições instaladas, permite pular somente o
próprio projeto editável e exige versão exata, zero dependência omitida e zero vulnerabilidade. Erro
do auditor, JSON parcial, distribuição duplicada ou skip adicional bloqueia o gate.

O `uv.lock` é o lock autoritativo do projeto. A opção `pip-audit --locked` não é usada porque ela não
consome esse formato; a completude é provada pela comparação do relatório com o ambiente sincronizado.
Não há ignore de vulnerabilidade aprovado pela F7.3.

## Diagnóstico

- Cobertura: execute primeiro a full suite e depois o checker; não edite o manifesto para acomodar a
  falha.
- Secrets: remova a credencial e faça sua rotação. Só atualize o baseline para fixture deliberada já
  revisada.
- Dependências: atualize a restrição e o lock para uma versão corrigida; não adicione ignore genérico.
- CI: preserve os nomes e a dependência dos quatro jobs no `CI required`, além dos actions fixados por
  SHA e das permissões read-only.
