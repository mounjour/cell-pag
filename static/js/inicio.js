/* Tela inicial: abas "Vence hoje" (todas/pendentes/pagas) e "Últimos pagamentos" (todos/Pix/dinheiro). */
(() => {
  document.querySelectorAll("[data-ic-abas]").forEach((abas) => {
    const chave = abas.dataset.icAbas;
    const lista = document.querySelector(`[data-ic-lista="${chave}"]`);
    if (!lista) return;
    abas.addEventListener("click", (e) => {
      const aba = e.target.closest(".ic-tab");
      if (!aba) return;
      abas.querySelectorAll(".ic-tab").forEach((t) => t.setAttribute("aria-selected", String(t === aba)));
      const filtro = aba.dataset.f;
      let visiveis = 0;
      lista.querySelectorAll("[data-f]").forEach((linha) => {
        const mostrar = filtro === "todos" || linha.dataset.f === filtro;
        linha.hidden = !mostrar;
        if (mostrar) visiveis += 1;
      });
      const vazio = lista.querySelector("[data-ic-vazio]");
      if (vazio) vazio.hidden = visiveis > 0;
      if (chave === "metodo") {
        const total = document.querySelector("[data-ic-total]");
        const nome = document.querySelector("[data-ic-nome]");
        if (total) total.textContent = aba.dataset.total;
        if (nome) nome.textContent = filtro === "todos" ? "Pix e dinheiro" : aba.textContent.trim();
      }
    });
  });
})();
