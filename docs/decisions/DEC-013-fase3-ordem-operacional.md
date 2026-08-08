# DEC-013 — Ordem operacional restante da Fase 3

> **Estado:** aceita
> **Data:** 2026-08-08
> **Autoridade:** autorização explícita para continuar com o gate F3.4 após auditoria da Fase 3

## Contexto

O plano descrevia F3.4 como a próxima tarefa após o realinhamento F3.C1/F3.C2, mas a tabela global de
implementação agrupava F3.4–F3.5 depois de F3.6. A formulação era ambígua: o path guard pode existir
como primitiva independente, enquanto terminal e edição só podem operar depois que um worktree real
fornecer a raiz autorizada.

F3.C2 também deixou o registry operacional vazio. Portanto, criar o contrato de confinamento agora
não habilita efeito algum e não antecipa worktree, terminal, promoção ou edição.

## Decisão

1. F3.4 implementa somente um `PathGuard` reutilizável, construído com uma raiz autorizada explícita.
2. O guard resolve e normaliza paths, segue symlinks/junctions existentes, rejeita travessia e escape,
   bloqueia escrita em `.git`, aplica limites de tamanho e devolve somente o path relativo normalizado
   destinado ao journal.
3. F3.4 não cria worktree, não registra tools, não executa comandos e não altera adapters legados.
4. F3.6 cria e valida o worktree Git real e instancia o guard com a raiz canônica resultante.
5. F3.5 e F3.8 só podem habilitar terminal/edição depois de F3.4 e F3.6, usando o guard imediatamente
   antes do efeito. F3.7 mantém sua dependência de F3.6 e F4.7.
6. A ordem operacional restante é `F3.4 → F3.6 → F3.5 → F3.8`, com F3.7 executada quando F4.7 também
   estiver promovida. Numeração de tarefa não substitui dependências explícitas.

## Consequências

- A saída do realinhamento DEC-012 pode ser certificada no primeiro commit de F3.4.
- Nenhum adapter inseguro passa a ser capacidade operacional por causa deste gate.
- Tests da F3.4 usam uma raiz temporária explícita; integração com worktree pertence a F3.6.
- Qualquer tentativa de integrar terminal, Serena, Git, promoção ou edição na F3.4 é mudança de escopo
  e bloqueia o gate.

## Alternativas rejeitadas

- **Executar F3.6 antes de F3.4:** mistura a criação do isolamento com o contrato que consumidores
  deverão obedecer e contradiz a saída nominal da DEC-012.
- **Habilitar adapters junto com o guard:** antecipa F3.5/F3.8 e expõe efeitos antes do worktree real.
- **Usar `cwd` ou raiz implícita:** permite que o chamador valide contra o checkout errado.

## Verificação

- o plano e o painel apontam F3.4 como tarefa ativa;
- o dossiê F3.4 proíbe adapters, processos, Git e registrations;
- a auditoria de escopo compara essas fronteiras com `checkpoint/f3.4-ready`;
- F3.5/F3.6/F3.8 devem citar esta decisão em seus próprios gates.
