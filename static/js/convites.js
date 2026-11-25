// Tela de convites: copiar link/código com um clique.
(() => {
  const avisar = (texto, tipo = "success") => {
    if (window.notificar) window.notificar(texto, tipo, { chave: "convite-copia" });
  };
  const copiarTexto = async (texto) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texto);
      return;
    }
    const campo = document.createElement("textarea");
    campo.value = texto;
    campo.setAttribute("readonly", "");
    campo.style.position = "fixed";
    campo.style.opacity = "0";
    document.body.append(campo);
    campo.select();
    const ok = document.execCommand("copy");
    campo.remove();
    if (!ok) throw new Error("copia");
  };
  document.addEventListener("click", async (evento) => {
    const botao = evento.target.closest("[data-copiar]");
    if (!botao) return;
    try {
      await copiarTexto(botao.dataset.copiar);
      avisar(botao.dataset.copiarAviso || "Copiado.");
    } catch (erro) {
      avisar("Não foi possível copiar. Selecione o link e copie manualmente.", "error");
    }
  });
  document.querySelectorAll("[data-selecionar]").forEach((campo) => {
    campo.addEventListener("focus", () => campo.select());
  });
})();
