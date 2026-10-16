(function () {
  var raiz = document.getElementById("semana");
  if (!raiz) return;
  var faixa = raiz.querySelector(".faixa");
  var todos = raiz.querySelector(".faixa-todos");
  var botoes = Array.prototype.slice.call(raiz.querySelectorAll(".faixa-todos, .faixa-dia.tem"));
  var listas = raiz.querySelectorAll(".semana-lista");
  var reduz = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var setas = [];

  function seta(direcao) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "faixa-seta";
    b.setAttribute("aria-label", direcao < 0 ? "Dia anterior" : "Próximo dia");
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + (direcao < 0 ? "m15 5-7 7 7 7" : "m9 5 7 7-7 7") + '"/></svg>';
    b.addEventListener("click", function () {
      var i = botoes.indexOf(raiz.querySelector(".faixa-todos.ativo, .faixa-dia.ativo"));
      var alvo = botoes[i + direcao];
      if (alvo) selecionar(alvo);
    });
    return b;
  }

  function posicionarSetas(b) {
    setas.forEach(function (s) { s.remove(); });
    setas = [];
    var i = botoes.indexOf(b);
    if (i > 0 || b !== todos) {
      if (i > 0) { var esq = seta(-1); faixa.insertBefore(esq, b); setas.push(esq); }
    }
    if (i < botoes.length - 1) { var dir = seta(1); faixa.insertBefore(dir, b.nextSibling); setas.push(dir); }
  }

  function selecionar(b) {
    var dia = b.getAttribute("data-dia");
    botoes.forEach(function (o) {
      var ativo = o === b;
      o.classList.toggle("ativo", ativo);
      o.setAttribute("aria-pressed", ativo ? "true" : "false");
    });
    posicionarSetas(b);
    var ordem = 0;
    listas.forEach(function (l) {
      var mostrar = dia === "todos" || l.getAttribute("data-dia") === dia;
      l.hidden = !mostrar;
      l.classList.remove("entrando");
      if (mostrar && !reduz) {
        l.style.setProperty("--i", Math.min(ordem++, 8));
        void l.offsetWidth;
        l.classList.add("entrando");
      }
    });
    // Leva o bloco escolhido para o meio da faixa, depois que ele termina de crescer.
    window.setTimeout(function () {
      var alvo = b.offsetLeft - (faixa.clientWidth - b.offsetWidth) / 2;
      faixa.scrollTo({ left: Math.max(0, alvo), behavior: reduz ? "auto" : "smooth" });
    }, reduz ? 0 : 290);
  }

  botoes.forEach(function (b) {
    b.addEventListener("click", function () { selecionar(b); });
  });
  posicionarSetas(todos);
})();
