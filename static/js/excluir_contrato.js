(() => {
  const abrir = document.getElementById("abrir-excluir-contrato");
  const dialogo = document.getElementById("dialog-excluir-contrato");
  if (!abrir || !dialogo) return;
  const formulario = dialogo.querySelector("form");
  const cancelar = dialogo.querySelector("[data-cancelar-exclusao]");
  const confirmar = dialogo.querySelector('[type="submit"]');
  const erro = dialogo.querySelector("[data-erro-exclusao]");
  let enviando = false;

  abrir.addEventListener("click", () => {
    erro.hidden = true;
    dialogo.showModal();
  });
  cancelar.addEventListener("click", () => dialogo.close());
  dialogo.addEventListener("close", () => abrir.focus());
  dialogo.addEventListener("cancel", (evento) => {
    if (enviando) evento.preventDefault();
  });
  formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (enviando || !dialogo.open) return;
    enviando = true;
    cancelar.disabled = confirmar.disabled = true;
    confirmar.textContent = "Excluindo…";
    formulario.setAttribute("aria-busy", "true");
    erro.hidden = true;
    try {
      const resposta = await fetch(formulario.action, {
        method: "POST",
        body: new FormData(formulario),
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const dados = await resposta.json();
      if (!resposta.ok || !dados.redirect_url) throw new Error("exclusao");
      window.location.assign(dados.redirect_url);
    } catch (_) {
      erro.textContent = "Não foi possível confirmar a exclusão. Confira sua conexão e atualize a página para verificar o contrato antes de tentar novamente.";
      erro.hidden = false;
      enviando = false;
      cancelar.disabled = confirmar.disabled = false;
      confirmar.textContent = "Excluir contrato";
      formulario.removeAttribute("aria-busy");
      cancelar.focus();
    }
  });
})();
