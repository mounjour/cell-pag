// Linha ou cartão com data-href: clicar em qualquer parte abre o destino.
// Links, botões e campos dentro dele continuam funcionando normalmente.
(() => {
  document.addEventListener("click", (evento) => {
    const alvo = evento.target.closest("[data-href]");
    if (!alvo || evento.target.closest("a, button, input, select, textarea, label, summary, form")) return;
    if (window.getSelection && String(window.getSelection())) return; // não rouba seleção de texto
    const destino = alvo.dataset.href;
    if (evento.ctrlKey || evento.metaKey) window.open(destino, "_blank", "noopener");
    else window.location.assign(destino);
  });
})();
