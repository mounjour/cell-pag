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
})();
