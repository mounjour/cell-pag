(function () {
  var raiz = document.getElementById("assistente");
  if (!raiz) return;
  var lista = document.getElementById("assistente-lista");
  var form = document.getElementById("assistente-form");
  var texto = document.getElementById("assistente-texto");
  var botaoEnviar = document.getElementById("assistente-enviar");
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";

  function rolar() { lista.scrollTop = lista.scrollHeight; window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }

  function balao(papel, conteudo) {
    var d = document.createElement("div");
    d.className = "assistente__msg assistente__msg--" + papel;
    d.textContent = conteudo;
    lista.appendChild(d);
    rolar();
    return d;
  }

  function post(url, corpo) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
      body: corpo ? JSON.stringify(corpo) : "{}",
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, dados: j }; }); });
  }

  function mostrarDecisao(cartao, acao) {
    cartao.className = "assistente__acao assistente__acao--" + acao.estado;
    cartao.textContent = "";
    var selo = document.createElement("span");
    selo.className = "pill " + (acao.estado === "confirmada" ? "pago" : acao.estado === "cancelada" ? "cancelado" : "inadimplente");
    selo.textContent = acao.estado_rotulo;
    cartao.appendChild(selo);
    cartao.appendChild(document.createTextNode(" " + acao.resumo + (acao.resultado ? " — " + acao.resultado : "")));
  }

  function ligarBotoes(cartao) {
    cartao.querySelectorAll("button[data-decisao]").forEach(function (b) {
      b.addEventListener("click", function () {
        cartao.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
        post(b.getAttribute("data-url")).then(function (r) {
          if (r.ok) { mostrarDecisao(cartao, r.dados); }
          else {
            cartao.querySelectorAll("button").forEach(function (x) { x.disabled = false; });
            var erro = document.createElement("p");
            erro.className = "assistente__aviso";
            erro.textContent = r.dados.erro || "Não foi possível concluir.";
            cartao.appendChild(erro);
          }
        });
      });
    });
  }

  function cartaoDeAcao(acao) {
    var c = document.createElement("div");
    c.className = "assistente__acao assistente__acao--pendente";
    var p = document.createElement("p");
    p.textContent = acao.resumo;
    c.appendChild(p);
    (acao.avisos || []).forEach(function (a) {
      var av = document.createElement("p");
      av.className = "assistente__aviso";
      av.textContent = a;
      c.appendChild(av);
    });
    var botoes = document.createElement("div");
    botoes.className = "assistente__botoes";
    [["confirmar", "Confirmar", "btn-mini btn-mini--pagar"], ["cancelar", "Cancelar", "btn-mini"]].forEach(function (par) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = par[2];
      b.textContent = par[1];
      b.setAttribute("data-decisao", par[0]);
      b.setAttribute("data-url", "/assistente/acao/" + acao.id + "/" + par[0] + "/");
      botoes.appendChild(b);
    });
    c.appendChild(botoes);
    ligarBotoes(c);
    return c;
  }

  lista.querySelectorAll(".assistente__acao--pendente").forEach(ligarBotoes);
  rolar();

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var conteudo = texto.value.trim();
      if (!conteudo || raiz.getAttribute("data-pronto") !== "1") return;
      var vazio = lista.querySelector(".assistente__vazio");
      if (vazio) vazio.remove();
      balao("usuario", conteudo);
      texto.value = "";
      texto.disabled = botaoEnviar.disabled = true;
      var pensando = balao("assistente", "Pensando…");
      pensando.classList.add("assistente__msg--pensando");
      post(raiz.getAttribute("data-enviar"), { texto: conteudo }).then(function (r) {
        pensando.remove();
        if (!r.ok) { balao("erro", r.dados.erro || "Não consegui responder agora."); return; }
        balao("assistente", r.dados.resposta);
        (r.dados.acoes || []).forEach(function (a) { lista.appendChild(cartaoDeAcao(a)); });
        rolar();
      }).catch(function () {
        pensando.remove();
        balao("erro", "Sem conexão com o servidor. Tente de novo.");
      }).then(function () {
        texto.disabled = botaoEnviar.disabled = false;
        texto.focus();
      });
    });
    texto.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
  }
})();
