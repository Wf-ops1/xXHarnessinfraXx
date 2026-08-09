# DEC-014 — Reconciliação documental imediata pós-merge

> **Estado:** aceita
> **Data:** 2026-08-08
> **Autoridade:** solicitação explícita para manter painel, dossiê e documentação atualizados após cada merge

## Contexto

A DEC-011 e o ciclo Git anterior adiavam a certificação de uma tarefa promovida até o primeiro commit
do gate seguinte. A regra evitava um PR recursivo exclusivamente para registrar o próprio merge, mas
mantinha `TASK.md`, o dossiê ativo e o README conscientemente defasados entre tarefas. Depois do merge
da F3.5, por exemplo, Git/GitHub já comprovavam PR #27, merge `b6a4a24` e CI pós-merge verde, enquanto
o painel ainda solicitava publicação e autorização de merge.

O painel operacional não pode chamar esse intervalo de alinhado. A preferência explícita do usuário é
que a atualização documental seja parte obrigatória do encerramento, e não trabalho oculto adiado para
a próxima implementação.

## Decisão

1. Merge de implementação e CI pós-merge verde iniciam uma pausa obrigatória; nenhuma tarefa seguinte
   pode ser congelada ou implementada nesse intervalo.
2. O executor cria imediatamente `docs/promote-<id>` a partir da `main` sincronizada e registra no
   dossiê anterior o head final do PR, CI do PR, merge commit e CI de `push` no SHA exato.
3. A mesma reconciliação marca o dossiê `PROMOTED`, move-o para `docs/tasks/completed/`, atualiza o
   ledger, `TASK.md`, README e os testes de estado/documentação afetados.
4. A branch possui um PR administrativo próprio. Ele não conta como segundo PR de implementação e é
   estritamente proibido de alterar código de produto, dependências, schemas, defaults ou CI.
5. Push, abertura e merge do PR administrativo continuam efeitos externos sujeitos às autorizações
   explícitas normais. Se não estiverem autorizados, o agente prepara e valida localmente, registra a
   pendência com clareza e pausa; nunca declara a documentação de `main` atualizada antes do merge.
6. A próxima tarefa só pode começar depois do merge dessa reconciliação, de sua CI em `main` verde e de
   nova autorização nominal para o gate seguinte.
7. O PR administrativo não cria reconciliação recursiva de si mesmo. Ele certifica somente a tarefa de
   implementação anterior; seu próprio merge passa a compor o baseline Git do próximo gate.

## Consequências

- O estado versionado em `main` passa a distinguir imediatamente tarefa promovida de tarefa planejada.
- Cada tarefa de implementação ganha um pequeno PR documental adicional e duas autorizações externas
  adicionais (publicação/abertura e merge), privilegiando rastreabilidade sobre velocidade.
- O dossiê seguinte nasce somente depois de a reconciliação anterior estar incorporada e verde.
- Evidência histórica não é reescrita silenciosamente: falhas e estados intermediários permanecem no
  dossiê, seguidos por uma certificação final explícita.

## Verificação

- não existe dossiê de implementação ativo durante a pausa entre tarefas;
- `TASK.md` declara a próxima tarefa apenas como planejada e informa a autorização nominal necessária;
- o dossiê promovido contém PR/checks/merge/run exatos e está indexado em `completed/`;
- testes de ledger falham se o painel voltar a solicitar um efeito remoto já comprovadamente concluído;
- o diff da reconciliação não contém `src/`, dependência, schema, default ou workflow de CI.
