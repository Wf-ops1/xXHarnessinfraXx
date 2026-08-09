# AI-Engineering-Harness — Regras Operacionais dos Agentes

## Estado atual

Este projeto ainda é um protótipo arquitetural em evolução para um harness operacional. A fórmula
`BMAD → Graph Engineering → MAF → Serena + Codebase-Memory → Quality/Ops` representa a arquitetura desejada, não uma lista de integrações já funcionais.

## Fontes de verdade

Antes de qualquer ação, ler integralmente:

1. `TASK.md` — painel curto com estado atual, bloqueios, executor, última promoção e próxima ação.
2. O único dossiê ativo apontado por `TASK.md`, quando houver — problema, evidências, escopo, aceite e rollback.
3. A fase ativa e as seções 1.1–1.2 de `docs/plano_implementacao_harness_operacional.md` — requisitos,
   ciclo Git e contrato normativo do gate `READY`.

O histórico concluído está indexado em `docs/tasks/README.md` e só precisa ser aberto quando a tarefa
atual depender daquela evidência. Não recarregar todos os dossiês concluídos por padrão.

Em caso de conflito, o pedido explícito do usuário prevalece; depois, o plano principal; por fim, o checkpoint em `TASK.md` deve ser atualizado para refletir a decisão.

## Coordenação obrigatória

1. Apenas um agente pode ser executor/escritor por vez.
2. Se outro agente estiver registrado como executor ativo em `TASK.md`, atuar somente em auditoria e não editar arquivos.
3. Antes de editar código, concluir F0.0 e registrar `python_command`, estado Git e workspace.
4. Atualizar o dossiê ativo com arquivos, comandos, validações, decisões, rollback e checkpoint;
   manter no `TASK.md` somente estado corrente, bloqueios, última promoção e próxima ação.
5. Nunca depender apenas do histórico da conversa para retomar trabalho.

## Gate de defensabilidade

1. O contrato completo está na seção 1.2 do plano principal e não pode ser reduzido por este resumo.
2. O gate começa `BLOCKED`. Antes do primeiro arquivo de implementação, o dossiê deve comprovar
   problema, baseline, escopo e critérios congelados, rollback, executor, runtime e horário; somente
   então muda para `READY` e recebe checkpoint Git.
3. Critério que falhou nunca pode ser removido, ignorado ou enfraquecido. Novo arquivo, efeito,
   dependência ou critério exige parar e recongelar o dossiê; ampliação material exige novo checkpoint.
4. Rollback deve ser não destrutivo. `git reset --hard`, descarte amplo e sobrescrita de trabalho
   preexistente não são autorizados pelo dossiê.
5. Evidência negativa nova sempre prevalece sobre sucesso anterior. Antes do merge, reabrir o aceite
   como `REPAIR_ACTIVE / PROMOTION_BLOCKED`; depois do merge, preservar o fato histórico `PROMOTED`,
   mas marcar o estado corrente `POST_PROMOTION_BLOCKED` e bloquear qualquer gate seguinte.
6. Recertificação e restauração de estado positivo só podem ocorrer depois de corrigir sem enfraquecer
   critérios, repetir todo o aceite aplicável e reconciliar painel/dossiê com SHA, run, resultado e
   horário realmente observados.
7. Antes de escrever `READY`, `COMPLETED_LOCAL`, `PROMOTION_PENDING`, `PROMOTED` ou “verde”, revalidar
   Git/workspace, testes/aceite, CI aplicável e documentos. Intenção, execução iniciada ou amostra
   anterior não são prova do estado corrente.

## Git e recuperação

1. Verificar a existência de `.git` antes de executar `git status`, `git diff`, `git log` ou qualquer operação Git.
2. Se `.git` estiver ausente, não executar `git init` automaticamente. Registrar bloqueio e pedir decisão explícita ao usuário.
3. Quando Git estiver disponível, preservar mudanças existentes e criar checkpoints por tarefa.
4. Nunca apagar, resetar ou sobrescrever trabalho de outro agente para resolver conflito.
5. A partir da F2.1, criar uma branch `task/<id>-<descricao-curta>` para cada tarefa, sempre a partir
   de `main` sincronizada, com a tarefa anterior já incorporada e CI pós-merge verde.
6. Nunca desenvolver diretamente em `main` nem iniciar a tarefa seguinte sobre branch ainda não
   incorporada. Uma branch pode conter vários commits da mesma tarefa, mas não acumular tarefas futuras.
7. Cada tarefa concluída deve ter um único PR para `main`, branch atualizada e `CI required=success`.
   Preferir merge commit para preservar histórico e permitir revert isolado da tarefa.
8. Push, abertura de PR, merge, exclusão de branch/tag remota, force-push, bypass ou mudança de
   proteção exigem autorização explícita do usuário. Force-push e bypass não são o fluxo normal.
9. Depois dos gates locais, manter o dossiê em `active/` como
   `COMPLETED_LOCAL / PROMOTION_PENDING`; isso não autoriza iniciar a tarefa seguinte.
10. Depois do merge e da CI pós-merge verde no SHA exato de `main`, iniciar imediatamente uma
    reconciliação administrativa em `docs/promote-<id>`: registrar PR/checks/merge/run, marcar o
    dossiê `PROMOTED`, movê-lo para `completed/`, atualizar índice, painel, README e testes de estado.
11. A reconciliação pós-merge possui PR documental próprio, não conta como segundo PR de implementação
    e não pode alterar produto, dependências, schemas ou CI. Push, abertura e merge continuam exigindo
    autorização explícita. Nenhum gate seguinte começa antes de esse PR e sua CI em `main` ficarem
    verdes. O próprio PR administrativo não exige outro PR recursivo; ele encerra a certificação.
12. Outras mudanças documentais transversais usam `docs/<descricao-curta>` e um único PR próprio.

O ciclo completo e suas exceções estão em `docs/plano_implementacao_harness_operacional.md`, seção
`Ciclo Git obrigatório por tarefa`. A F1 é a exceção histórica já concluída em uma branch linear;
o commit que adota esta regra acompanha a branch da F1 antes de seu PR. Nenhuma implementação da F2
começa antes dessa promoção para `main` e do CI pós-merge verde.

## Ambiente de execução

1. Não assumir que `python`, `py` ou `uv` existem.
2. Detectar o ambiente, selecionar Python `>=3.11` e registrar o comando no painel e no dossiê ativo.
3. Usar o comando registrado nos critérios de aceite; não trocar de runtime silenciosamente.
4. Instalação de runtime, dependências globais ou ferramentas requer autorização quando alterar o ambiente do usuário.

## Layout real durante a transição

- Código do pacote: `src/ai_engineering_harness/`.
- Grafos distribuídos: `src/ai_engineering_harness/defaults/graphs/`.
- Políticas distribuídas: `src/ai_engineering_harness/defaults/policies/`.
- Contratos: `src/ai_engineering_harness/contracts/`.
- Configuração copiada para projetos-alvo: `.harness/`.
- Compilador oficial: `src/ai_engineering_harness/compiler/`, concluído na Fase 1.

`compiler/compile.py` é somente um wrapper de compatibilidade que delega ao package. Paths de raiz
como `graphs/specs/`, `contracts/` e `policies/` continuam legados/inconsistentes e não são fonte de
verdade.

## Implementação e verificação

1. Não criar mocks ou respostas simuladas em código de produção.
2. Não declarar Serena, Codebase-Memory, MAF, provider, doctor, gate, promoção ou rollback como funcional sem efeito real e teste correspondente.
3. Integração indisponível deve falhar com erro explícito, não retornar sucesso sintético.
4. Executar os critérios de aceite definidos no dossiê ativo.
5. Alterações exclusivamente documentais não exigem compilar um grafo legado; devem ser validadas
   recursivamente quanto a encoding, links, consistência e Markdown.
6. Uma tarefa só pode ser marcada `completed` depois que todas as verificações aplicáveis passarem.

## Painel e arquivo de dossiês — DEC-010

1. `TASK.md` é painel operacional, não arquivo histórico, e deve permanecer com no máximo 300 linhas.
2. Existe no máximo um dossiê em `docs/tasks/active/`, além do README: a tarefa corrente ou a última
   tarefa em `COMPLETED_LOCAL / PROMOTION_PENDING`.
3. Somente dossiês certificados como `PROMOTED` ficam em `docs/tasks/completed/`, um por tarefa/PR e indexados por
   `docs/tasks/README.md`; os 19 dossiês migrados do painel legado são cobertos pelo manifesto.
4. Dossiê concluído é evidência imutável. Correção exige PR documental explícito e atualização de
   integridade; nunca reescrever silenciosamente resultado, erro, SHA, PR ou run.
5. Não duplicar no painel contratos completos, logs, checklists concluídos ou histórico de fases.
6. Entre o merge de implementação e a reconciliação administrativa, o painel pode apontar o dossiê
   `PROMOTION_PENDING`, mas deve declarar que não há implementação ativa. A reconciliação pós-merge
   certifica/arquiva esse dossiê imediatamente; somente depois de seu merge e CI verde o próximo gate
   pode ser criado como `READY` antes do primeiro arquivo de implementação.
7. O painel registra o último estado realmente observado. Se houver atraso inevitável entre um evento
   externo e seu commit documental, declarar explicitamente a pendência; nunca apresentar o snapshot
   anterior como atual nem usar linguagem absoluta como “100% alinhado”.
