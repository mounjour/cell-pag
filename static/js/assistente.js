(function () {
  var raiz = document.getElementById("assistente");
  if (!raiz) return;
  var abrir = document.getElementById("assistente-abrir");
  var painel = document.getElementById("assistente-painel");
  var fechar = document.getElementById("assistente-fechar");
  var nova = document.getElementById("assistente-nova");
  var lista = document.getElementById("assistente-lista");
  var form = document.getElementById("assistente-form");
  var texto = document.getElementById("assistente-texto");
  var enviar = document.getElementById("assistente-enviar");
  var ponto = document.getElementById("assistente-ponto");
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";
  var carregado = false;
  var pronto = true;

  function rolar() { lista.scrollTop = lista.scrollHeight; }

  function balao(papel, conteudo) {
    var d = document.createElement("div");
    d.className = "assistente__msg assistente__msg--" + papel;
    d.textContent = conteudo;
    lista.appendChild(d);
    rolar();
    return d;
  }

  function pedir(url, corpo) {
    return fetch(url, {
      method: corpo === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo || {}),
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, dados: j }; }); });
  }

  function pendentes() { return lista.querySelectorAll(".assistente__acao--pendente").length; }
  function atualizarPonto() { ponto.hidden = pendentes() === 0; }

  function rotuloDoEstado(estado) { return estado === "confirmada" ? "pago" : estado === "cancelada" ? "cancelado" : "inadimplente"; }

  function mostrarDecisao(cartao, acao) {
    cartao.className = "assistente__acao assistente__acao--" + acao.estado;
    cartao.textContent = "";
    var selo = document.createElement("span");
    selo.className = "pill " + rotuloDoEstado(acao.estado);
    selo.textContent = acao.estado_rotulo;
    cartao.appendChild(selo);
    cartao.appendChild(document.createTextNode(" " + acao.resumo + (acao.resultado ? " — " + acao.resultado : "")));
    atualizarPonto();
  }

  function decidir(cartao, botao) {
    cartao.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
    pedir(botao.getAttribute("data-url"), {}).then(function (r) {
      if (r.ok) { mostrarDecisao(cartao, r.dados); return; }
      cartao.querySelectorAll("button").forEach(function (x) { x.disabled = false; });
      var erro = document.createElement("p");
      erro.className = "assistente__aviso";
      erro.textContent = r.dados.erro || "Não foi possível concluir.";
      cartao.appendChild(erro);
    });
  }

  function cartaoPendente(acao) {
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
    [["Confirmar", acao.confirmar_url, "btn-mini btn-mini--pagar"], ["Cancelar", acao.cancelar_url, "btn-mini"]].forEach(function (par) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = par[2];
      b.textContent = par[0];
      b.setAttribute("data-url", par[1]);
      b.addEventListener("click", function () { decidir(c, b); });
      botoes.appendChild(b);
    });
    c.appendChild(botoes);
    return c;
  }

  function cartaoDecidido(acao) {
    var c = document.createElement("div");
    mostrarDecisao(c, acao);
    return c;
  }

  function dica() {
    var d = document.createElement("p");
    d.className = "assistente__vazio";
    d.textContent = "Eu consulto o sistema e proponho registros (pagamento, contato, bloqueio). Só gravo quando você clicar em Confirmar. Ex.: “quem está atrasado?”, “Roberto pagou 157,50 no Pix hoje”.";
    return d;
  }

  function carregar() {
    lista.textContent = "";
    pedir(raiz.getAttribute("data-historico")).then(function (r) {
      carregado = true;
      if (!r.ok) { balao("erro", "Não consegui carregar a conversa."); return; }
      var d = r.dados;
      pronto = !!d.configurado;
      if (!pronto) balao("erro", "O assistente ainda não foi ligado: falta a chave da API no servidor.");
      if (!d.mensagens.length && !d.pendentes.length && !d.decididas.length) lista.appendChild(dica());
      d.mensagens.forEach(function (m) { balao(m.papel, m.texto); });
      d.decididas.forEach(function (a) { lista.appendChild(cartaoDecidido(a)); });
      d.pendentes.forEach(function (a) { lista.appendChild(cartaoPendente(a)); });
      texto.disabled = enviar.disabled = !pronto;
      atualizarPonto();
      rolar();
    }).catch(function () { balao("erro", "Sem conexão com o servidor."); });
  }

  var fechando = null;
  function abrirPainel() {
    clearTimeout(fechando);
    painel.hidden = false;
    abrir.setAttribute("aria-expanded", "true");
    window.requestAnimationFrame(function () { painel.classList.add("assistente-painel--aberto"); });
    if (!carregado) carregar();
    window.setTimeout(function () { if (!texto.disabled) texto.focus(); }, 200);
  }
  function fecharPainel() {
    painel.classList.remove("assistente-painel--aberto");
    abrir.setAttribute("aria-expanded", "false");
    fechando = window.setTimeout(function () { painel.hidden = true; }, 220);
    abrir.focus();
  }

  abrir.addEventListener("click", function () { if (painel.hidden) abrirPainel(); else fecharPainel(); });
  fechar.addEventListener("click", fecharPainel);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !painel.hidden) fecharPainel(); });

  nova.addEventListener("click", function () {
    if (!window.confirm("Começar uma nova conversa? As propostas ainda pendentes serão canceladas.")) return;
    pedir(raiz.getAttribute("data-nova"), {}).then(function () { carregado = false; carregar(); });
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var conteudo = texto.value.trim();
    if (!conteudo || !pronto) return;
    var vazio = lista.querySelector(".assistente__vazio");
    if (vazio) vazio.remove();
    balao("usuario", conteudo);
    texto.value = "";
    texto.disabled = enviar.disabled = true;
    var pensando = balao("assistente", "Pensando…");
    pensando.classList.add("assistente__msg--pensando");
    pedir(raiz.getAttribute("data-enviar"), { texto: conteudo }).then(function (r) {
      pensando.remove();
      if (!r.ok) { balao("erro", r.dados.erro || "Não consegui responder agora."); return; }
      balao("assistente", r.dados.resposta);
      (r.dados.acoes || []).forEach(function (a) { lista.appendChild(cartaoPendente(a)); });
      atualizarPonto();
      rolar();
    }).catch(function () {
      pensando.remove();
      balao("erro", "Sem conexão com o servidor. Tente de novo.");
    }).then(function () {
      texto.disabled = enviar.disabled = false;
      texto.focus();
    });
  });
  texto.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
})();
