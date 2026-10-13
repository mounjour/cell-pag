(() => {
  document.addEventListener("submit", (evento) => {
    const formulario = evento.target;
    if (!(formulario instanceof HTMLFormElement) || formulario.dataset.enviando) return;
    if (!formulario.checkValidity()) return;
    formulario.dataset.enviando = "1";
    // Um botão desabilitado não envia o seu name/value. Muitos formulários dependem do botão
    // clicado (ex.: acao=confirmar), então o valor vai num campo oculto antes de desabilitar.
    const clicado = evento.submitter;
    if (clicado && clicado.name) {
      const oculto = document.createElement("input");
      oculto.type = "hidden";
      oculto.name = clicado.name;
      oculto.value = clicado.value;
      formulario.append(oculto);
    }
    for (const botao of formulario.querySelectorAll('button[type="submit"]')) {
      botao.dataset.rotulo = botao.textContent.trim();
      botao.disabled = true;
      botao.textContent = "Salvando…";
    }
  });
})();
