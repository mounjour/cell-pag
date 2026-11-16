/* Menus suspensos (usuário e "Mais") e atalho de busca.
   - Clicar fora ou apertar Esc fecha os menus; abrir um fecha o outro.
   - A tecla "/" leva o cursor para a busca (fora de campos de texto). */
(function () {
  function menus() { return document.querySelectorAll("details.menu-pop"); }

  document.addEventListener("click", function (ev) {
    menus().forEach(function (d) {
      if (d.open && !d.contains(ev.target)) d.open = false;
    });
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      menus().forEach(function (d) { d.open = false; });
      return;
    }
    if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var alvo = ev.target;
    var digitando = alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName));
    if (digitando) return;
    var campo = document.querySelector("[data-busca-global]");
    if (campo && campo.offsetParent !== null) {
      ev.preventDefault();
      campo.focus();
      campo.select();
    }
  });

  menus().forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (!d.open) return;
      menus().forEach(function (outro) { if (outro !== d) outro.open = false; });
    });
  });

  /* Barrinha do menu lateral: uma só, que desliza até a página atual.
     Ao clicar ela já corre para o item novo; na página seguinte ela parte de onde estava. */
  var nav = document.querySelector(".sidebar .nav");
  if (nav && nav.offsetParent !== null) { // no celular o menu lateral não existe
    var marcador = document.createElement("span");
    marcador.className = "nav-marcador";
    marcador.setAttribute("aria-hidden", "true");
    nav.insertBefore(marcador, nav.firstChild);

    var CHAVE_MARCADOR = "marcadorLateral";
    var guardado = function () { try { return sessionStorage.getItem(CHAVE_MARCADOR); } catch (e) { return null; } };
    var guardar = function (v) { try { sessionStorage.setItem(CHAVE_MARCADOR, String(v)); } catch (e) { /* sem armazenamento: só não parte do item anterior */ } };

    var posicao = function (link) {
      var h = Math.round(link.offsetHeight * 0.56);
      return { y: link.offsetTop + Math.round((link.offsetHeight - h) / 2), h: h };
    };
    var colocar = function (pos, animar) {
      if (!animar) marcador.classList.add("sem-transicao");
      marcador.style.height = pos.h + "px";
      marcador.style.transform = "translateY(" + pos.y + "px)";
      marcador.classList.add("visivel");
      if (!animar) {
        void marcador.offsetHeight; // aplica sem animar antes de religar a transição
        marcador.classList.remove("sem-transicao");
      }
    };

    var ativo = nav.querySelector("a.active");
    if (ativo) {
      var destino = posicao(ativo);
      var antes = parseFloat(guardado());
      if (!isNaN(antes) && Math.abs(antes - destino.y) > 1) {
        colocar({ y: antes, h: destino.h }, false);
        void marcador.offsetHeight; // fixa o ponto de partida antes de mandar deslizar
        colocar(destino, true);
      } else {
        colocar(destino, false);
      }
      guardar(destino.y);
      // Quando o menu recolhe ou abre, os itens mudam de lugar: a barrinha acompanha sem animar à parte.
      if (window.ResizeObserver) {
        var altura = nav.offsetHeight;
        new ResizeObserver(function () {
          if (nav.offsetHeight === altura) return; // a primeira chamada não muda nada: deixa a barrinha deslizar
          altura = nav.offsetHeight;
          var atual = nav.querySelector("a.active");
          if (atual) colocar(posicao(atual), false);
        }).observe(nav);
      }
    }

    nav.addEventListener("click", function (ev) {
      var link = ev.target.closest && ev.target.closest("a");
      if (!link || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
      var pos = posicao(link);
      colocar(pos, true);
      guardar(pos.y);
    });
  }
})();
