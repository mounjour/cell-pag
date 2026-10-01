(() => {
  const abrir = document.querySelector("[data-confirmar-exclusao]");
  const dialogo = document.getElementById("dialog-excluir-cliente");
  const formulario = document.getElementById("form-excluir-cliente");
  if (!abrir || !dialogo || !formulario) return;
  abrir.addEventListener("click", () => dialogo.showModal());
  dialogo.querySelector("[data-cancelar-exclusao]").addEventListener("click", () => dialogo.close());
  dialogo.querySelector("[data-confirmar-exclusao-final]").addEventListener("click", () => formulario.requestSubmit());
})();
