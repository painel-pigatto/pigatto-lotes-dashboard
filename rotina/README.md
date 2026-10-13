# Rotina agendada — Alerta Quinzenal de Vencimento de Lotes (Grupo Pigatto)

Cópia de referência da Routine do Claude Code que gera os alertas de vencimento de lotes.
A rotina **continua rodando na nuvem**; este arquivo é só o registro versionado da definição.

| Campo | Valor |
|---|---|
| ID da Routine | `trig_01BSxLZcFuMN8htbJTmR6gja` |
| Nome | Alerta Quinzenal de Vencimento de Lotes — Grupo Pigatto |
| Agenda (cron, UTC) | `0 11 1,15 * *` → dias 1 e 15, ~08:00 (Brasília) |
| Status | Ativa |
| Criada em | 17/09/2026 (a pedido do Head de Operações) |
| Última alteração | 06/10/2026 |
| Última execução | 01/10/2026 11:00 UTC — sucesso |
| Próxima execução | 15/10/2026 |
| Modelo | claude-sonnet-5 · modo de permissão `auto` |
| Conectores | Gmail, Claude Docs, Google Drive, Claude Code Remote |
| Notificações | push + e-mail |

## Histórico de mudanças

- **17/09/2026** — criada como rotina **mensal** (todo dia 1º).
- **01/10/2026** — passa a **quinzenal** (dias 1 e 15); destinatários do e-mail de vencidos reduzidos a operação + atendimento; enriquecimento de lotes de bisnagas com Ordem de Produção (Passo 3B); novo 3º rascunho de revalidação LORD para a Parker (Passo 6B), corrigido duas vezes no mesmo dia após testes reais.
- **06/10/2026** — mostra a validade revalidada pela Parker Lord (ou a negativa) nos lotes diretos e nos lotes de matéria-prima citados nas OPs (Passo 3C).

## O que a rotina faz (resumo)

1. Puxa todos os lotes do Omie (`ListarLotes`) e a família de cada produto (`ConsultarProduto`).
2. Filtra lotes com saldo que vencem nos próximos 90 dias e lotes **já vencidos** com saldo.
3. Classifica em tabelas: A (Adesivos Estruturais + Linha TT), B (Chemlok, Bio-Chem, Marbocote), C (outras famílias).
4. Para bisnagas (lote = nº da OP), troca a célula Lote por "OP nº X / Lotes nº …" lendo as observações da OP.
5. Para lotes LORD, mostra o status de revalidação da Parker (lê o doc `claude/Revalidacao_Lotes_LORD_ParkerLord.md` e, se preciso, o PDF do certificado no Gmail).
6. Cria **rascunhos** no Gmail (nunca envia):
   - Alerta 90 dias → comercial (caixas do comercial; cópia para diretoria, operação, atendimento e qualidade).
   - URGENTE lotes vencidos → operação e atendimento (só se houver).
   - Solicitação de revalidação → contato de Qualidade da Parker, só para lotes LORD diretos < 30 dias, nunca repetidos, nunca de produtos fabricados internamente.
7. Registra o log em `claude/Processo_Alerta_Vencimento_Lotes_2026-09.md` (projeto "Grupo Pigatto").

O prompt completo, palavra por palavra, está em [`prompt.md`](prompt.md).

> **Segurança:** o prompt original da Routine contém `app_key`/`app_secret` do Omie em texto puro.
> Nesta cópia eles foram substituídos por `<OMIE_APP_KEY>` / `<OMIE_APP_SECRET>`. As credenciais nunca devem
> ser commitadas neste repositório (ele é público).
