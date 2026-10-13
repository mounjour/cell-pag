/* Registrar pagamento: ao escolher a parcela inicial ou quantas parcelas o pagamento quita,
   o valor e o juros são preenchidos com a soma delas (continuam editáveis). */
(function () {
  var form = document.querySelector('form[data-previsao-url]');
  if (!form || !form.elements.quantidade) return;
  var qtd = form.elements.quantidade, venc = form.elements.vencimento;
  var valor = form.elements.valor_pago, juros = form.elements.juros_pago;
  var parcelas = JSON.parse(qtd.dataset.parcelas || '[]');

  function inicio() {
    var i = parcelas.findIndex(function (p) { return String(p.id) === venc.value; });
    return i < 0 ? 0 : i;
  }
  function formatar(n) { return n.toFixed(2).replace('.', ','); }
  function limitar() {
    var restantes = parcelas.length - inicio();
    Array.prototype.forEach.call(qtd.options, function (o) { o.hidden = o.disabled = (parseInt(o.value, 10) > restantes); });
    if (parseInt(qtd.value, 10) > restantes) qtd.value = String(restantes);
  }
  function recalcular() {
    limitar();
    var x = parseInt(qtd.value, 10) || 1, soma = 0, jur = 0;
    parcelas.slice(inicio(), inicio() + x).forEach(function (p) { soma += parseFloat(p.saldo); jur += parseFloat(p.juros); });
    valor.value = formatar(soma);
    juros.value = formatar(jur);
    [valor, juros].forEach(function (c) { c.dispatchEvent(new Event('input', { bubbles: true })); });
  }
  qtd.addEventListener('change', recalcular);
  venc.addEventListener('change', recalcular);
  limitar();
})();
