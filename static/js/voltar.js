/* "Voltar": usa o histórico quando a página anterior é do próprio sistema e
   não é um formulário (senão voltaria para "Novo/Editar" depois de salvar);
   caso contrário segue o destino de reserva do próprio link. */
(function () {
  var FORMULARIO = /\/(novo|editar)\/?$/;
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest && ev.target.closest("a[data-voltar]");
    if (!link || ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
    var ref;
    try { ref = document.referrer ? new URL(document.referrer) : null; } catch (e) { ref = null; }
    if (!ref || ref.origin !== location.origin) return;
    if (ref.pathname === location.pathname || FORMULARIO.test(ref.pathname)) return;
    if (window.history.length < 2) return;
    ev.preventDefault();
    window.history.back();
  });
})();

/* Ao voltar, o navegador pode restaurar a página da memória (bfcache) sem
   recarregar — e a animação de entrada do conteúdo não roda. Reinicia-a. */
window.addEventListener("pageshow", function (ev) {
  if (!ev.persisted) return;
  var main = document.querySelector("main.wrap");
  if (!main) return;
  main.style.animation = "none";
  void main.offsetWidth; // força o reflow para a animação reiniciar
  main.style.animation = "";
});
