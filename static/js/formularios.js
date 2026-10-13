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

/* Campo numérico focado muda de valor com a roda do mouse (10 vira 9 ao rolar a página).
   Ao rolar com o cursor em cima dele, o campo perde o foco e a página rola normalmente. */
(() => {
  document.addEventListener("wheel", (evento) => {
    const campo = document.activeElement;
    if (campo instanceof HTMLInputElement && campo.type === "number" && campo === evento.target) campo.blur();
  }, { passive: true });
})();
