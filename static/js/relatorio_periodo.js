// Filtro do relatório: mexer em Início/Fim já significa "Personalizado".
// Sem isso o período "Diário" ignorava as datas e o relatório mostrava só 1 dia.
(function () {
  var periodo = document.getElementById("id_periodo");
  var inicio = document.getElementById("id_inicio");
  var fim = document.getElementById("id_fim");
  if (!periodo || !inicio || !fim) return;

  [inicio, fim].forEach(function (campo) {
    campo.addEventListener("change", function () {
      periodo.value = "personalizado";
    });
  });
})();
