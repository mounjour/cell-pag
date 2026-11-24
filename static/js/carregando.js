/* Liga o sombreado de carregamento ao navegar: clique em link interno ou envio de formulário.
   O estado sai sozinho se a página não trocar (download, erro, voltar do histórico). */
(function () {
  var corpo = document.body;
  var tempo = null;

  function ligar() {
    corpo.classList.add("carregando");
    clearTimeout(tempo);
    tempo = setTimeout(desligar, 15000);
  }
  function desligar() {
    clearTimeout(tempo);
    corpo.classList.remove("carregando");
  }

  document.addEventListener("click", function (ev) {
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^(javascript:|mailto:|tel:)/i.test(href)) return;
    var url;
    try { url = new URL(a.href, location.href); } catch (e) { return; }
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && url.search === location.search) return;
    ligar();
  });

  document.addEventListener("submit", function (ev) {
    setTimeout(function () {
      if (ev.defaultPrevented) return; // confirmação pendente ou validação barrou o envio
      var f = ev.target;
      if (f.target === "_blank" || (f.method || "").toLowerCase() === "dialog") return;
      ligar();
    }, 0);
  });

  window.addEventListener("pageshow", desligar);
})();
