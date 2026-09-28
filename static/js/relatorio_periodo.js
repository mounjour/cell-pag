// Filtro do relatório: mostra só os campos que valem para o período escolhido.
// "Personalizado" usa Início/Fim; os demais usam a Data de referência.
(function () {
  var periodo = document.getElementById("id_periodo");
  var referencia = document.getElementById("id_referencia");
  var inicio = document.getElementById("id_inicio");
  var fim = document.getElementById("id_fim");
  if (!periodo || !referencia || !inicio || !fim) return;

  function linha(campo) {
    return campo.closest(".form-row") || campo.parentElement;
  }

  function atualizar() {
    var custom = periodo.value === "personalizado";
    linha(referencia).hidden = custom;
    linha(inicio).hidden = !custom;
    linha(fim).hidden = !custom;
  }

  periodo.addEventListener("change", atualizar);
  atualizar();
})();
