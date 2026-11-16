/* Menu lateral recolhível (computador). Carregado no <head>, sem defer, para aplicar a escolha
   antes da primeira pintura (senão o menu pisca aberto e depois fecha).
   A escolha fica guardada neste navegador. */
(function () {
  var CHAVE = "lateral";
  var raiz = document.documentElement;

  function lido() {
    try { return localStorage.getItem(CHAVE); } catch (e) { return null; }
  }
  function guardar(valor) {
    try { localStorage.setItem(CHAVE, valor); } catch (e) { /* modo privado: vale só nesta visita */ }
  }
  function recolhida() { return raiz.getAttribute("data-lateral") === "recolhida"; }

  if (lido() === "recolhida") raiz.setAttribute("data-lateral", "recolhida");

  // Com o menu só de ícones, o nome de cada página aparece como dica ao passar o mouse.
  function sincronizar() {
    var r = recolhida();
    document.querySelectorAll("[data-lateral-toggle]").forEach(function (b) {
      b.setAttribute("aria-expanded", String(!r));
      b.setAttribute("aria-label", r ? "Expandir o menu lateral" : "Recolher o menu lateral");
      b.setAttribute("title", r ? "Expandir menu" : "Recolher menu");
    });
    document.querySelectorAll(".sidebar .nav a").forEach(function (a) {
      var nome = a.querySelector("span:not(.selo):not(.sr-only)");
      if (!nome) return;
      if (r) a.setAttribute("title", nome.textContent.trim());
      else a.removeAttribute("title");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    sincronizar();
    document.addEventListener("click", function (ev) {
      var botao = ev.target.closest && ev.target.closest("[data-lateral-toggle]");
      if (!botao) return;
      if (recolhida()) raiz.removeAttribute("data-lateral");
      else raiz.setAttribute("data-lateral", "recolhida");
      guardar(recolhida() ? "recolhida" : "aberta");
      sincronizar();
      // Gráficos e quadros que medem a largura se ajustam quando o menu termina de mexer.
      setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 320);
    });
  });
})();
