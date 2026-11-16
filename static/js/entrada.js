/* Tela de entrada: botão de mostrar/esconder a senha. */
(() => {
  document.querySelectorAll("[data-mostrar-senha]").forEach((botao) => {
    const campo = botao.closest(".login-input").querySelector("input");
    if (!campo) return;
    botao.addEventListener("click", () => {
      const mostrar = campo.type === "password";
      campo.type = mostrar ? "text" : "password";
      botao.setAttribute("aria-pressed", String(mostrar));
      botao.setAttribute("aria-label", mostrar ? "Esconder senha" : "Mostrar senha");
      botao.setAttribute("title", mostrar ? "Esconder senha" : "Mostrar senha");
      botao.classList.toggle("ligado", mostrar);
      campo.focus();
    });
  });
})();
