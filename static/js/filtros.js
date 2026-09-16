// Selects de filtro (?status=, ?estrutura=...) devem submeter o formulário
// sozinhos ao trocar de valor. Um atributo onchange="..." não roda — a CSP
// do site usa script-src 'self' sem 'unsafe-inline' (ver settings.py), então
// o listener precisa vir de um arquivo externo como este.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-auto-submit]").forEach(function (campo) {
    campo.addEventListener("change", function () {
      campo.form.submit();
    });
  });
});
