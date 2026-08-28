# Modelos de Contrato e Vencimento.
#
# AINDA NÃO IMPLEMENTADO. Depende de definições em aberto (PLANO-DO-PROJETO.md,
# seção 10 — Pendências):
#   - regra de cálculo do valor da parcela (R10);
#   - regra de vencimento de "por dezena" e "mensal" (R9 — NÃO DEFINIDO);
#   - folga na diária / marcação de atraso no semanal.
#
# Estrutura-alvo (PLANO-DO-PROJETO.md, seção 6):
#   Contrato   -> cliente, apelido, aparelho/IMEI, valor_total, estrutura,
#                 valor_parcela, num_parcelas, data_inicio, dia_referencia,
#                 status, data_prevista_quitacao
#   Vencimento -> contrato, numero, periodo_referencia, data_vencimento,
#                 valor_previsto, valor_pago, dias_atraso, status
