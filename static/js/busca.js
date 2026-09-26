/* Sugestões da busca enquanto se digita (campo do topo, no computador).
   - Só busca a partir de 2 caracteres, com espera de 200 ms entre as teclas;
     uma resposta antiga nunca sobrescreve uma mais nova.
   - Teclado: ↓/↑ escolhem, Enter abre o escolhido (sem escolha, vai para a
     página de resultados), Esc fecha.
   - Os textos entram como texto (textContent), nunca como HTML. */
(function () {
  var form = document.querySelector("form.busca[data-sugestoes-url]");
  if (!form) return;
  var campo = form.querySelector("input[data-busca-global]");
  var lista = form.querySelector("#busca-lista");
  var urlSugestoes = form.getAttribute("data-sugestoes-url");
  var MINIMO = 2;
  var espera = null;
  var pedido = null;
  var ativo = -1;
  var itens = [];

  function fechar() {
    lista.hidden = true;
    campo.setAttribute("aria-expanded", "false");
    campo.removeAttribute("aria-activedescendant");
    ativo = -1;
  }

  function marcar(indice) {
    itens.forEach(function (el, i) {
      el.classList.toggle("ativo", i === indice);
      el.setAttribute("aria-selected", i === indice ? "true" : "false");
    });
    ativo = indice;
    if (indice >= 0) {
      campo.setAttribute("aria-activedescendant", itens[indice].id);
      itens[indice].scrollIntoView({ block: "nearest" });
    } else {
      campo.removeAttribute("aria-activedescendant");
    }
  }

  function cabecalho(texto) {
    var el = document.createElement("div");
    el.className = "busca-grupo";
    el.setAttribute("role", "presentation");
    el.textContent = texto;
    return el;
  }

  function opcao(item, numero) {
    var a = document.createElement("a");
    a.className = "busca-item";
    a.href = item.url;
    a.id = "busca-opcao-" + numero;
    a.setAttribute("role", "option");
    a.setAttribute("aria-selected", "false");
    var titulo = document.createElement("span");
    titulo.className = "busca-item-titulo";
    titulo.textContent = item.titulo;
    var detalhe = document.createElement("span");
    detalhe.className = "busca-item-detalhe";
    detalhe.textContent = item.detalhe + (item.arquivado ? " · arquivado" : "");
    a.appendChild(titulo);
    a.appendChild(detalhe);
    return a;
  }

  function desenhar(dados) {
    lista.textContent = "";
    itens = [];
    var total = dados.clientes.length + dados.contratos.length;
    if (!total) {
      var vazio = document.createElement("div");
      vazio.className = "busca-vazio";
      vazio.textContent = "Nada encontrado para “" + dados.q + "”.";
      lista.appendChild(vazio);
    }
    [["Clientes", dados.clientes], ["Contratos", dados.contratos]].forEach(function (grupo) {
      if (!grupo[1].length) return;
      lista.appendChild(cabecalho(grupo[0]));
      grupo[1].forEach(function (item) {
        var el = opcao(item, itens.length);
        itens.push(el);
        lista.appendChild(el);
      });
    });
    if (total) {
      var todos = document.createElement("a");
      todos.className = "busca-item busca-todos";
      todos.href = form.getAttribute("action") + "?q=" + encodeURIComponent(dados.q);
      todos.id = "busca-opcao-" + itens.length;
      todos.setAttribute("role", "option");
      todos.setAttribute("aria-selected", "false");
      todos.textContent = "Ver todos os resultados para “" + dados.q + "”";
      itens.push(todos);
      lista.appendChild(todos);
    }
    lista.hidden = false;
    campo.setAttribute("aria-expanded", "true");
    ativo = -1;
  }

  function buscar() {
    var q = campo.value.trim();
    if (q.length < MINIMO) { fechar(); return; }
    if (pedido) pedido.abort();
    pedido = new AbortController();
    fetch(urlSugestoes + "?q=" + encodeURIComponent(q), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: pedido.signal,
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (dados) {
        if (dados.q === campo.value.trim()) desenhar(dados); // ignora resposta velha
      })
      .catch(function () { /* cancelada ou sem rede: o Enter ainda leva à página de resultados */ });
  }

  campo.addEventListener("input", function () {
    clearTimeout(espera);
    espera = setTimeout(buscar, 200);
  });

  campo.addEventListener("focus", function () {
    if (itens.length && campo.value.trim().length >= MINIMO) {
      lista.hidden = false;
      campo.setAttribute("aria-expanded", "true");
    }
  });

  campo.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      if (!lista.hidden) { ev.stopPropagation(); fechar(); }
      return;
    }
    if (lista.hidden || !itens.length) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      marcar(ativo + 1 >= itens.length ? 0 : ativo + 1);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      marcar(ativo <= 0 ? itens.length - 1 : ativo - 1);
    } else if (ev.key === "Enter" && ativo >= 0) {
      ev.preventDefault();
      window.location.href = itens[ativo].href;
    }
  });

  // Clicar fora fecha; clicar numa sugestão segue o link normalmente.
  document.addEventListener("click", function (ev) {
    if (!form.contains(ev.target)) fechar();
  });
  form.addEventListener("submit", function () { clearTimeout(espera); if (pedido) pedido.abort(); });
})();
