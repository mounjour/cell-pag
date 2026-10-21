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
  var entradaArquivo = document.getElementById("assistente-arquivo");
  var botaoAnexar = document.getElementById("assistente-anexar");
  var areaAnexos = document.getElementById("assistente-anexos");
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";
  var carregado = false;
  var pronto = true;
  var anexos = [];
  var MAX_ARQUIVOS = 4;
  var MAX_BYTES = 4500000;

  function rolar() { lista.scrollTop = lista.scrollHeight; }

  function balao(papel, conteudo) {
    var d = document.createElement("div");
    d.className = "assistente__msg assistente__msg--" + papel;
    d.textContent = conteudo;
    lista.appendChild(d);
    rolar();
    return d;
  }

  function balaoUsuario(conteudo, nomes, miniaturas) {
    var d = balao("usuario", conteudo);
    if (!nomes || !nomes.length) return d;
    var caixa = document.createElement("div");
    caixa.className = "assistente__msg-anexos";
    nomes.forEach(function (nome, i) {
      var item = document.createElement("span");
      item.className = "assistente__msg-anexo";
      if (miniaturas && miniaturas[i]) {
        var img = document.createElement("img");
        img.src = miniaturas[i];
        img.alt = "";
        item.appendChild(img);
      }
      item.appendChild(document.createTextNode(nome));
      caixa.appendChild(item);
    });
    d.appendChild(caixa);
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

  var SUGESTOES = [
    { rotulo: "Quem está atrasado hoje?", texto: "Quem está atrasado hoje?", enviar: true },
    { rotulo: "Cobranças dos próximos dias", texto: "Quais são as cobranças dos próximos 7 dias?", enviar: true },
    { rotulo: "Ver o status de um cliente", texto: "Status do cliente ", enviar: false },
    { rotulo: "Registrar um pagamento", texto: "Registrar pagamento: ", enviar: false },
    { rotulo: "Anotar uma promessa", texto: "Anotar que o cliente prometeu pagar dia ", enviar: false },
  ];

  function dica() {
    var c = document.createElement("div");
    c.className = "assistente__boasvindas";
    var t = document.createElement("h3");
    var nome = raiz.getAttribute("data-nome");
    t.textContent = "Olá" + (nome ? ", " + nome : "") + "! Sou o assistente do sistema.";
    c.appendChild(t);
    var p = document.createElement("p");
    p.textContent = "Converse comigo em português. Eu consulto clientes, parcelas, atrasos e próximas cobranças, e preparo registros para você. Também leio imagens e PDFs, como um comprovante de Pix: é só anexar.";
    c.appendChild(p);
    var ul = document.createElement("ul");
    [
      "Pagamentos: eu monto o registro com parcela, valor e juros.",
      "Contatos e promessas de pagamento.",
      "Bloqueio e liberação de aparelhos.",
    ].forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = item;
      ul.appendChild(li);
    });
    c.appendChild(ul);
    var seguro = document.createElement("p");
    seguro.className = "assistente__boasvindas-seguro";
    seguro.textContent = "Nada é gravado sem você clicar em Confirmar. Não apago nem estorno nada, e não envio mensagens a clientes.";
    c.appendChild(seguro);
    var rotulo = document.createElement("p");
    rotulo.className = "assistente__boasvindas-rotulo";
    rotulo.textContent = "Experimente:";
    c.appendChild(rotulo);
    var chips = document.createElement("div");
    chips.className = "assistente__chips";
    SUGESTOES.forEach(function (sug) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "assistente__chip";
      b.textContent = sug.rotulo;
      b.addEventListener("click", function () {
        if (sug.enviar) { texto.value = sug.texto; form.requestSubmit(); return; }
        texto.value = sug.texto;
        ajustarAltura();
        texto.focus();
        texto.setSelectionRange(texto.value.length, texto.value.length);
      });
      chips.appendChild(b);
    });
    c.appendChild(chips);
    return c;
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
      d.mensagens.forEach(function (m) {
        if (m.papel === "usuario") balaoUsuario(m.texto, m.anexos); else balao(m.papel, m.texto);
      });
      d.decididas.forEach(function (a) { lista.appendChild(cartaoDecidido(a)); });
      d.pendentes.forEach(function (a) { lista.appendChild(cartaoPendente(a)); });
      texto.disabled = enviar.disabled = botaoAnexar.disabled = !pronto;
      atualizarPonto();
      if (lista.querySelector(".assistente__boasvindas")) lista.scrollTop = 0; else rolar();
    }).catch(function () { balao("erro", "Sem conexão com o servidor."); });
  }

  /* ── anexos ─────────────────────────────────────────────────────────────── */

  function nomeCurto(nome) { return nome.length > 28 ? nome.slice(0, 25) + "…" : nome; }

  function tipoAceito(arquivo) {
    return /^image\/(png|jpeg|webp|gif)$/.test(arquivo.type) || arquivo.type === "application/pdf" || /\.(txt|csv)$/i.test(arquivo.name);
  }

  function leitura(arquivo) {
    return new Promise(function (ok) {
      var leitor = new FileReader();
      leitor.onload = function () { ok(leitor.result); };
      leitor.onerror = function () { ok(null); };
      leitor.readAsDataURL(arquivo);
    });
  }

  // Foto grande do celular é reduzida antes de enviar: o comprovante continua legível e o envio fica rápido.
  function reduzir(arquivo) {
    if (!/^image\/(png|jpeg|webp)$/.test(arquivo.type) || arquivo.size < 1000000) return Promise.resolve(arquivo);
    return leitura(arquivo).then(function (url) {
      if (!url) return arquivo;
      return new Promise(function (ok) {
        var img = new Image();
        img.onload = function () {
          var fator = Math.min(1, 1600 / Math.max(img.width, img.height));
          var c = document.createElement("canvas");
          c.width = Math.round(img.width * fator);
          c.height = Math.round(img.height * fator);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(function (blob) {
            if (!blob || blob.size >= arquivo.size) { ok(arquivo); return; }
            ok(new File([blob], arquivo.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }));
          }, "image/jpeg", 0.85);
        };
        img.onerror = function () { ok(arquivo); };
        img.src = url;
      });
    });
  }

  function desenharAnexos() {
    areaAnexos.textContent = "";
    areaAnexos.hidden = anexos.length === 0;
    anexos.forEach(function (arquivo, i) {
      var chip = document.createElement("span");
      chip.className = "assistente__anexo";
      if (arquivo.type.indexOf("image/") === 0) {
        leitura(arquivo).then(function (url) {
          if (!url) return;
          var img = document.createElement("img");
          img.src = url;
          img.alt = "";
          chip.insertBefore(img, chip.firstChild);
        });
      }
      chip.appendChild(document.createTextNode(nomeCurto(arquivo.name)));
      var x = document.createElement("button");
      x.type = "button";
      x.className = "assistente__anexo-x";
      x.setAttribute("aria-label", "Remover " + arquivo.name);
      x.textContent = "×";
      x.addEventListener("click", function () { anexos.splice(i, 1); desenharAnexos(); });
      chip.appendChild(x);
      areaAnexos.appendChild(chip);
    });
  }

  function adicionarArquivos(lote) {
    Array.prototype.slice.call(lote).forEach(function (arquivo) {
      if (anexos.length >= MAX_ARQUIVOS) { balao("erro", "No máximo " + MAX_ARQUIVOS + " arquivos por mensagem."); return; }
      if (!tipoAceito(arquivo)) { balao("erro", "“" + arquivo.name + "”: só aceito imagens, PDF e arquivos .txt ou .csv."); return; }
      reduzir(arquivo).then(function (final) {
        if (final.size > MAX_BYTES) { balao("erro", "“" + arquivo.name + "” é grande demais (máximo 4,5 MB)."); return; }
        if (anexos.length >= MAX_ARQUIVOS) return;
        anexos.push(final);
        desenharAnexos();
      });
    });
  }

  botaoAnexar.addEventListener("click", function () { entradaArquivo.click(); });
  entradaArquivo.addEventListener("change", function () { adicionarArquivos(entradaArquivo.files); entradaArquivo.value = ""; });
  texto.addEventListener("paste", function (e) {
    var itens = (e.clipboardData && e.clipboardData.files) || [];
    if (itens.length) { e.preventDefault(); adicionarArquivos(itens); }
  });
  painel.addEventListener("dragover", function (e) { e.preventDefault(); painel.classList.add("assistente-painel--arrastando"); });
  painel.addEventListener("dragleave", function (e) { if (e.target === painel) painel.classList.remove("assistente-painel--arrastando"); });
  painel.addEventListener("drop", function (e) {
    e.preventDefault();
    painel.classList.remove("assistente-painel--arrastando");
    if (e.dataTransfer && e.dataTransfer.files.length) adicionarArquivos(e.dataTransfer.files);
  });

  function ajustarAltura() {
    texto.style.height = "auto";
    texto.style.height = Math.min(texto.scrollHeight, 112) + "px";
  }
  texto.addEventListener("input", ajustarAltura);

  /* ── abrir e fechar ─────────────────────────────────────────────────────── */

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

  /* ── envio ──────────────────────────────────────────────────────────────── */

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var conteudo = texto.value.trim();
    if ((!conteudo && !anexos.length) || !pronto) return;
    var vazio = lista.querySelector(".assistente__boasvindas");
    if (vazio) vazio.remove();
    var enviados = anexos.slice();
    Promise.all(enviados.map(function (a) { return a.type.indexOf("image/") === 0 ? leitura(a) : Promise.resolve(null); })).then(function (miniaturas) {
      balaoUsuario(conteudo, enviados.map(function (a) { return nomeCurto(a.name); }), miniaturas);
    });
    var dados = new FormData();
    dados.append("texto", conteudo);
    enviados.forEach(function (a) { dados.append("arquivos", a, a.name); });
    texto.value = "";
    ajustarAltura();
    anexos = [];
    desenharAnexos();
    texto.disabled = enviar.disabled = botaoAnexar.disabled = true;
    var pensando = balao("assistente", "Pensando…");
    pensando.classList.add("assistente__msg--pensando");
    fetch(raiz.getAttribute("data-enviar"), { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf }, body: dados })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, dados: j }; }); })
      .then(function (r) {
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
        texto.disabled = enviar.disabled = botaoAnexar.disabled = false;
        texto.focus();
      });
  });
  texto.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
})();
