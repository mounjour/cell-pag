/* Contatos de cobrança: a data da promessa só aparece quando o resultado é "Prometeu pagar",
   e apagar uma anotação pede confirmação. */
(function () {
  document.querySelectorAll('[data-contato-form]').forEach(function (form) {
    var resultado = form.querySelector('select[name="resultado"]');
    var bloco = form.querySelector('[data-contato-promessa]');
    var data = form.querySelector('input[name="promessa_para"]');
    if (!resultado || !bloco) return;
    function atualizar() {
      var promessa = resultado.value === 'promessa';
      bloco.hidden = !promessa;
      if (data) data.required = promessa;
    }
    resultado.addEventListener('change', atualizar);
    atualizar();
  });
  document.querySelectorAll('form[data-confirmar]').forEach(function (form) {
    form.addEventListener('submit', function (evento) {
      if (!window.confirm(form.dataset.confirmar)) evento.preventDefault();
    });
  });
})();
