/* Acompanha o estado do WhatsApp ao vivo (polling), em qualquer página.

   - Mostra um aviso (toast) quando conecta ou desconecta.
   - Atualiza os selos do menu/sino na hora, sem recarregar.
   - Na tela Conexões, troca o cartão do WhatsApp (conectado ↔ desconectado).
   O servidor responde da cache (alguns segundos), então várias abas não
   sobrecarregam a Evolution. Pausa com a aba escondida e retoma ao voltar. */
(() => {
  const url = document.body.dataset.conexoesStatusUrl;
  if (!url) return;

  const CHAVE = "whatsapp_estado";
  const cartao = () => document.querySelector("[data-conexoes-card]");
  const INTERVALO = () => (cartao() ? 4000 : 15000);

  const lerAnterior = () => {
    try { return sessionStorage.getItem(CHAVE); } catch (e) { return null; }
  };
  const guardar = (estado) => {
    try { sessionStorage.setItem(CHAVE, estado); } catch (e) { /* sem storage: só perde o aviso entre páginas */ }
  };

  const aplicarSelos = (desconectado) => {
    document.querySelectorAll("[data-whatsapp-selo]").forEach((el) => { el.hidden = !desconectado; });
    const item = document.querySelector("[data-whatsapp-notificacao]");
    if (!item) return;
    const estavaVisivel = !item.hidden;
    item.hidden = !desconectado;
    if (estavaVisivel === desconectado) return;
    const contador = document.querySelector("[data-notificacoes-n]");
    const selo = document.querySelector("[data-notificacoes-selo]");
    const total = Math.max(0, (parseInt(contador && contador.textContent, 10) || 0) + (desconectado ? 1 : -1));
    if (contador) contador.textContent = String(total);
    if (selo) selo.hidden = total === 0;
    const vazio = document.querySelector("[data-notificacoes-vazio]");
    if (vazio) vazio.hidden = total > 0;
  };

  const atualizarCartao = async () => {
    const atual = cartao();
    if (!atual) return;
    try {
      const resposta = await fetch(window.location.href, { credentials: "same-origin" });
      if (!resposta.ok) return;
      const novo = new DOMParser().parseFromString(await resposta.text(), "text/html").querySelector("[data-conexoes-card]");
      if (novo) atual.replaceWith(novo);
    } catch (e) { /* tenta de novo na próxima mudança */ }
  };

  const avisar = (anterior, estado) => {
    if (!window.notificar || anterior === null || anterior === estado) return;
    if (estado === "open") {
      window.notificar("WhatsApp conectado. As cobranças automáticas voltam a sair.", "success", { chave: "whatsapp" });
    } else if (anterior === "open") {
      window.notificar("WhatsApp desconectado. As cobranças automáticas estão paradas.", "error", {
        href: document.body.dataset.conexoesUrl,
        rotulo: "Reconectar",
        chave: "whatsapp",
      });
    }
  };

  const consultar = async () => {
    if (document.hidden) return;
    let estado;
    try {
      const resposta = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!resposta.ok) return;
      estado = (await resposta.json()).estado;
    } catch (e) { return; }

    if (estado === "simulado") return;
    const anterior = lerAnterior();
    aplicarSelos(estado !== "open");
    if (anterior !== estado) {
      avisar(anterior, estado);
      if ((anterior === "open") !== (estado === "open")) atualizarCartao();
    }
    guardar(estado);
  };

  const ciclo = async () => {
    await consultar();
    window.setTimeout(ciclo, INTERVALO());
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) consultar(); });
  ciclo();
})();
