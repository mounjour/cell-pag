/* Tema claro/escuro. Carregado no <head>, sem defer, para aplicar a escolha
   antes da primeira pintura (senão a página pisca no tema errado).

   - Logado: o tema fica salvo na conta (o servidor já entrega o <html> com
     data-tema; o clique grava via POST em data-tema-url).
   - Sem login (tela de entrada): vale a escolha guardada neste navegador.
   O padrão é o claro. */
(function () {
  var CHAVE = "tema";
  var raiz = document.documentElement;
  var urlConta = raiz.getAttribute("data-tema-url"); // só existe com login

  function lido() {
    try { return localStorage.getItem(CHAVE); } catch (e) { return null; }
  }
  function guardar(valor) {
    try { localStorage.setItem(CHAVE, valor); } catch (e) { /* modo privado: vale só nesta visita */ }
  }
  function escuro() { return raiz.getAttribute("data-tema") === "escuro"; }

  function sincronizar() {
    var e = escuro();
    var cor = document.querySelector('meta[name="theme-color"]');
    if (cor) cor.setAttribute("content", e ? "#0f1115" : "#ffffff");
    document.querySelectorAll("[data-tema-toggle]").forEach(function (b) {
      b.setAttribute("aria-label", e ? "Ativar modo claro" : "Ativar modo escuro");
      b.setAttribute("title", e ? "Modo claro" : "Modo escuro");
    });
  }

  function gravarNaConta(tema) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return fetch(urlConta, {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": meta ? meta.getAttribute("content") : "",
      },
      body: "tema=" + encodeURIComponent(tema),
    }).catch(function () { /* sem rede: a tela já mudou; tenta de novo no próximo clique */ });
  }

  if (urlConta) {
    // O servidor manda: a tela de entrada, no mesmo aparelho, passa a refletir a conta.
    guardar(escuro() ? "escuro" : "claro");
  } else if (lido() === "escuro") {
    raiz.setAttribute("data-tema", "escuro");
  }

  document.addEventListener("DOMContentLoaded", function () {
    sincronizar();
    document.addEventListener("click", function (ev) {
      var botao = ev.target.closest && ev.target.closest("[data-tema-toggle]");
      if (!botao) return;
      var novo = escuro() ? "claro" : "escuro";
      if (novo === "escuro") raiz.setAttribute("data-tema", "escuro");
      else raiz.removeAttribute("data-tema");
      guardar(novo);
      sincronizar();
      var pronto = urlConta ? gravarNaConta(novo) : Promise.resolve();
      // Os gráficos leem as cores uma vez, ao desenhar: redesenha a página.
      if (document.querySelector("canvas")) pronto.then(function () { window.location.reload(); });
    });
  });
})();
