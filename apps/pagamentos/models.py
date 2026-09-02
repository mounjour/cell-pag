# Modelos de Pagamento e Cobranca.
#
# AINDA NÃO IMPLEMENTADO. As regras que faltavam já foram decididas
# (PLANO-DO-PROJETO.md, seções 5, 8 e 10):
#   - pagamento parcial (Q16): aceito; o saldo não pago soma no próximo pagamento do contrato;
#   - canal de cobrança (Bloco 5): Modalidade A (lembrete para a Yslane às 08:30) na v1;
#   - juros/multa (Q26-Q29): R$ 5,00 fixos por dia de atraso; aos 7 dias -> alerta de bloqueio (ação manual);
#   - configuração de canal/mensagem é global, sem variação por cliente (Q20).
# Continua dependendo da Fase 2: o vínculo pagamento->parcela (model Vencimento),
# que só existe depois que o Alisson fechar o cálculo da parcela e as regras de
# diária / por dezena / mensal.
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
