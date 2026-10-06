/* Busca ao vivo na lista de clientes: filtra enquanto se digita (sem botão).
   Recarrega a página com o termo (mantém filtro e "arquivados") e devolve o
   foco ao campo, com o cursor no fim, para continuar digitando. */
(() => {
  const campo = document.querySelector("[data-busca-clientes]");
  if (!campo) return;
  const formulario = campo.form;
  let espera;

  campo.addEventListener("input", () => {
    window.clearTimeout(espera);
    espera = window.setTimeout(() => formulario.requestSubmit(), 350);
  });

  // Voltou de uma busca: o foco volta ao campo, com o cursor depois do texto.
  if (new URLSearchParams(window.location.search).has("q") && document.activeElement === document.body) {
    campo.focus({ preventScroll: true });
    const fim = campo.value.length;
    campo.setSelectionRange(fim, fim);
  }
})();
