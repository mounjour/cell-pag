(() => {
  const area = document.getElementById("mensagens");
  if (!area) return;
  area.classList.add("toast-area");
  const adicionar = (texto, tipo = "info") => {
    const mensagem = document.createElement("li");
    mensagem.className = `msg ${tipo}`;
    mensagem.textContent = texto;
    area.append(mensagem);
    preparar(mensagem);
  };
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
  document.addEventListener("click", (evento) => {
    const botao = evento.target.closest("[data-demo-notificacao]");
    if (botao) {
      const [titulo, texto, tipo] = botao.dataset.demoNotificacao.split("|");
      adicionar(`${titulo}: ${texto}`, tipo);
    }
  });
})();
