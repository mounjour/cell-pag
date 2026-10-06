(() => {
  const area = document.getElementById("mensagens");
  if (!area) return;
  area.classList.add("toast-area");
  // Avisos com a mesma "chave" não se acumulam: o novo substitui o antigo.
  const fecharPorChave = (chave) => {
    area.querySelectorAll(`[data-chave="${chave}"]`).forEach((el) => el.remove());
  };
  const adicionar = (texto, tipo = "info", opcoes = {}) => {
    if (opcoes.chave) fecharPorChave(opcoes.chave);
    const mensagem = document.createElement("li");
    mensagem.className = `msg ${tipo}`;
    if (opcoes.chave) mensagem.dataset.chave = opcoes.chave;
    mensagem.setAttribute("role", tipo === "error" ? "alert" : "status");
    mensagem.append(document.createTextNode(texto));
    if (opcoes.href) {
      const link = document.createElement("a");
      link.href = opcoes.href;
      link.className = "toast-link";
      link.textContent = opcoes.rotulo || "Abrir";
      mensagem.append(" ", link);
    }
    area.append(mensagem);
    preparar(mensagem);
  };
  window.notificar = adicionar;
  window.fecharNotificacao = fecharPorChave;
  const preparar = (mensagem) => {
    const remover = () => {
      if (mensagem.classList.contains("toast-saindo")) return;
      mensagem.classList.add("toast-saindo");
      window.setTimeout(() => mensagem.remove(), 240);
    };
    const fechar = document.createElement("button");
    fechar.type = "button";
    fechar.className = "toast-fechar";
    fechar.setAttribute("aria-label", "Fechar notificação");
    fechar.textContent = "×";
    fechar.addEventListener("click", (evento) => {
      evento.preventDefault();
      evento.stopPropagation();
      remover();
    });
    mensagem.append(fechar);
    if (mensagem.classList.contains("success") || mensagem.classList.contains("info")) {
      window.setTimeout(remover, 5000);
    }
  };
  for (const mensagem of [...area.children]) preparar(mensagem);
})();
