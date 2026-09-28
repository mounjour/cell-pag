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

  function iso(data) {
    var m = String(data.getMonth() + 1).padStart(2, "0");
    var d = String(data.getDate()).padStart(2, "0");
    return data.getFullYear() + "-" + m + "-" + d;
  }

  // Ao escolher "Personalizado" sem datas, sugere os últimos 7 dias em vez de
  // deixar os campos vazios (que davam erro ao atualizar).
  function sugerirDatas() {
    if (inicio.value && fim.value) return;
    var hoje = new Date();
    var antes = new Date();
    antes.setDate(hoje.getDate() - 6);
    fim.value = fim.value || iso(hoje);
    inicio.value = inicio.value || iso(antes);
  }

  function atualizar() {
    var custom = periodo.value === "personalizado";
    linha(referencia).hidden = custom;
    linha(inicio).hidden = !custom;
    linha(fim).hidden = !custom;
    if (custom) sugerirDatas();
  }

  periodo.addEventListener("change", atualizar);
  atualizar();
})();
