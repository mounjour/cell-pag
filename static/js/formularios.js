(() => {
  document.addEventListener("submit", (evento) => {
    const formulario = evento.target;
    if (!(formulario instanceof HTMLFormElement) || formulario.dataset.enviando) return;
    if (!formulario.checkValidity()) return;
    formulario.dataset.enviando = "1";
    for (const botao of formulario.querySelectorAll('button[type="submit"]')) {
      botao.dataset.rotulo = botao.textContent.trim();
      botao.disabled = true;
      botao.textContent = "Salvando…";
    }
  });
})();
