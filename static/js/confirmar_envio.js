/* Formulários que mandam algo ao cliente (ou derrubam o WhatsApp) pedem confirmação antes. */
(function () {
  document.querySelectorAll("form[data-confirmar-envio]").forEach(function (form) {
    form.addEventListener("submit", function (evento) {
      if (!window.confirm(form.dataset.confirmarEnvio)) evento.preventDefault();
    });
  });
})();
