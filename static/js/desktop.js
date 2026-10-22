(function () {
  document.querySelectorAll("[data-copiar]").forEach(function (botao) {
    botao.addEventListener("click", function () {
      var alvo = document.querySelector(botao.getAttribute("data-copiar"));
      if (!alvo) return;
      var original = botao.innerHTML;
      var pronto = function () {
        botao.textContent = "Copiado!";
        window.setTimeout(function () { botao.innerHTML = original; }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(alvo.textContent).then(pronto);
      } else {
        var faixa = document.createRange();
        faixa.selectNodeContents(alvo);
        var selecao = window.getSelection();
        selecao.removeAllRanges();
        selecao.addRange(faixa);
        document.execCommand("copy");
        pronto();
      }
    });
  });
})();
