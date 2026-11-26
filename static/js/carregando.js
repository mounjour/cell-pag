/* Ao navegar (clique em link, linha clicável, busca ou envio de formulário), esconde a página
   atual e desenha o esqueleto sombreado da página de destino, escolhido pelo endereço.
   O estado sai sozinho se a página não trocar (erro, voltar do histórico). */
(function () {
  var conteudo = document.getElementById("conteudo");
  if (!conteudo) return;
  var corpo = document.body;
  var tempo = null;
  var camada = null;
  var rolagem = 0;
  var menuAntes = null;

  // Endereços que baixam um arquivo: a página não troca, então não há o que sombrear.
  var ARQUIVO = /\/(excel|pdf|conector|instalador|instalador-novo|baixar)\/$|\/comprovante\/\d+\/$/;

  // A ordem importa: vale o primeiro padrão que combinar com o caminho.
  var TIPOS = [
    [/\/(novo|editar|importar|confirmar|quitar|excluir|acordo)\/|\/pendencias\/\d+\/|^\/(entrar|cadastro)\//, "formulario"],
    [/^\/relatorios\//, "painel"],
    [/^\/(clientes|contratos|aparelhos)\/\d+\/$/, "detalhe"],
    [/\/(cobrar-hoje|bloqueios|conexoes|rotinas|ajuda|termos|convites|desktop)\//, "cartoes"],
  ];

  function tipoDe(caminho) {
    for (var i = 0; i < TIPOS.length; i++) if (TIPOS[i][0].test(caminho)) return TIPOS[i][1];
    return "lista";
  }

  function bloco(classe) { return '<span class="sk ' + classe + '"></span>'; }
  function repetir(vezes, html) { return new Array(vezes + 1).join(html); }
  function grupo(classe, html) { return '<div class="' + classe + '">' + html + "</div>"; }

  var TOPO = grupo("esq-topo",
    grupo("esq-pilha", bloco("esq-titulo") + bloco("esq-sub")) +
    grupo("esq-acoes", repetir(2, bloco("esq-botao"))));
  var LINHA = grupo("esq-linha",
    bloco("esq-avatar") + grupo("esq-pilha", bloco("esq-texto") + bloco("esq-texto esq-curto")) + bloco("esq-valor"));
  var CARTAO = grupo("esq-cartao", bloco("esq-texto esq-curto") + repetir(4, LINHA));
  var CAMPO = grupo("esq-pilha", bloco("esq-rotulo") + bloco("esq-campo"));

  var MODELOS = {
    lista: TOPO + bloco("esq-campo esq-filtro") + grupo("esq-abas", repetir(4, bloco("esq-aba"))) +
      grupo("esq-cartao", repetir(7, LINHA)),
    cartoes: TOPO + bloco("esq-faixa") + grupo("esq-abas", repetir(4, bloco("esq-aba"))) +
      grupo("esq-colunas", repetir(2, CARTAO)),
    painel: TOPO + grupo("esq-numeros", repetir(5, bloco("esq-numero"))) + bloco("esq-faixa") +
      grupo("esq-colunas", repetir(2, CARTAO)),
    detalhe: grupo("esq-topo",
        grupo("esq-quem", bloco("esq-avatar esq-avatar--grande") + grupo("esq-pilha", bloco("esq-titulo") + bloco("esq-sub"))) +
        grupo("esq-acoes", repetir(3, bloco("esq-botao")))) +
      grupo("esq-numeros", repetir(4, bloco("esq-numero"))) + grupo("esq-colunas", repetir(2, CARTAO)),
    formulario: grupo("esq-form",
      grupo("esq-pilha", bloco("esq-titulo") + bloco("esq-sub")) +
      repetir(2, grupo("esq-cartao", bloco("esq-texto esq-curto") + grupo("esq-colunas", repetir(4, CAMPO)))) +
      grupo("esq-acoes", repetir(2, bloco("esq-botao")))),
  };

  function ligar(url, tipo) {
    if (ARQUIVO.test(url.pathname)) return;
    if (!camada) {
      rolagem = window.scrollY;
      camada = document.createElement("div");
      camada.setAttribute("role", "status");
      camada.setAttribute("aria-label", "Carregando");
      conteudo.appendChild(camada);
    }
    camada.className = "esqueleto";
    camada.innerHTML = MODELOS[tipo || tipoDe(url.pathname)]; // só marcação fixa deste arquivo
    corpo.classList.add("carregando");
    window.scrollTo(0, 0);
    clearTimeout(tempo);
    tempo = setTimeout(desligar, 15000);
  }

  function desligar() {
    clearTimeout(tempo);
    if (menuAntes) { menuAntes(); menuAntes = null; }
    if (!camada) return;
    camada.remove();
    camada = null;
    corpo.classList.remove("carregando");
    window.scrollTo(0, rolagem);
  }

  // No menu, o destaque passa para o item clicado, junto com o esqueleto.
  function destacarNoMenu(link) {
    var menu = link.closest(".sidebar .nav, .tabbar");
    if (!menu || menuAntes) return;
    var atual = menu.querySelector(":scope > a.active");
    if (!link.matches(".nav > a, .tabbar > a")) return;
    if (atual) atual.classList.remove("active");
    link.classList.add("active");
    menuAntes = function () {
      link.classList.remove("active");
      if (atual) atual.classList.add("active");
    };
  }

  // Para quem navega por script (linha clicável, Enter na busca).
  function navegar(destino) {
    var url = new URL(destino, location.href);
    if (url.origin === location.origin) ligar(url);
    window.location.assign(url.href);
  }
  window.navegarCarregando = navegar;

  document.addEventListener("click", function (ev) {
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^(javascript:|mailto:|tel:)/i.test(href)) return;
    var url;
    try { url = new URL(a.href, location.href); } catch (e) { return; }
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
    if (ARQUIVO.test(url.pathname)) return;
    destacarNoMenu(a);
    ligar(url);
  });

  document.addEventListener("submit", function (ev) {
    var f = ev.target;
    var botao = ev.submitter;
    setTimeout(function () {
      if (ev.defaultPrevented) return; // confirmação pendente ou validação barrou o envio
      var metodo = ((botao && botao.getAttribute("formmethod")) || f.getAttribute("method") || "get").toLowerCase();
      if (f.target === "_blank" || metodo === "dialog") return;
      var action = (botao && botao.getAttribute("formaction")) || f.getAttribute("action") || location.href;
      var url = new URL(action, location.href);
      if (url.origin !== location.origin) return;
      if (metodo === "get") { ligar(url); return; }
      // Depois de um POST o servidor costuma voltar à própria tela; de um formulário, vai ao resultado.
      var tipo = tipoDe(location.pathname);
      if (tipo === "formulario") {
        if (/^\/(entrar|cadastro)\//.test(location.pathname)) tipo = "painel";
        else tipo = /^\/(clientes|contratos|aparelhos)\//.test(location.pathname) ? "detalhe" : "lista";
      }
      ligar(url, tipo);
    }, 0);
  });

  window.addEventListener("pageshow", desligar);
})();
