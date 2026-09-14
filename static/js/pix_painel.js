/* Botão "Copiar código" do Pix copia e cola. Tenta a Clipboard API; se não
   estiver disponível (contexto não seguro, navegador antigo), cai pro
   fallback de textarea temporária + execCommand. */
(function () {
  function copiar(texto) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texto);
    }
    var textarea = document.createElement("textarea");
    textarea.value = texto;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
    return Promise.resolve();
  }

  document.querySelectorAll(".btn-copiar-pix").forEach(function (botao) {
    var textoOriginal = botao.textContent;
    botao.addEventListener("click", function () {
      copiar(botao.dataset.pix)
        .then(function () {
          botao.textContent = "Copiado!";
          botao.classList.add("copiado");
        })
        .catch(function () {
          botao.textContent = "Não foi possível copiar";
        })
        .finally(function () {
          setTimeout(function () {
            botao.textContent = textoOriginal;
            botao.classList.remove("copiado");
          }, 1800);
        });
    });
  });
})();
