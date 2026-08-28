# Modelos de Pagamento e Cobranca.
#
# AINDA NÃO IMPLEMENTADO. Depende de definições em aberto (PLANO-DO-PROJETO.md,
# seção 10 — Pendências): vínculo pagamento->parcela ou saldo (Q15), pagamento
# parcial (Q16), canal de cobrança (Bloco 5), regras de juros/multa (Q26-Q29).
#
# Estrutura-alvo (PLANO-DO-PROJETO.md, seção 6):
#   Pagamento -> contrato, vencimento?, data_pagamento, valor_pago, forma,
#                usuario_baixa, comprovante?, tipo(total/parcial), observacao
#   Cobranca  -> contrato, data_alvo, canal(whatsapp/lembrete),
#                status(pendente/enviado/erro), mensagem, enviado_em
#
# Regras obrigatórias já conhecidas:
#   - UniqueConstraint(contrato, vencimento) no Pagamento (anti cobrança duplicada);
#   - registrar usuario_baixa + timestamp; auditoria via django-auditlog.
