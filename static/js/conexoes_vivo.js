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

  const aplicarTile = (estado) => {
    const tile = document.querySelector("[data-whatsapp-tile]");
    if (!tile) return;
    const ok = estado === "open";
    tile.classList.toggle("hoje-tile--alerta", !ok);
    tile.querySelector("[data-whatsapp-tile-valor]").textContent = ok ? "Conectado" : "Desconectado";
    tile.querySelector("[data-whatsapp-tile-sub]").textContent = ok ? "Cobranças saindo normalmente" : "Reconectar para voltar a cobrar";
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
    aplicarTile(estado);
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
  /* O cronômetro do QR é uma animação CSS: ao voltar à página (botão Voltar,
     cache de navegação, aba que ficou escondida) o navegador pode retomá-la de
     onde parou, sem passar pelo servidor. Buscar o cartão de novo traz o tempo
     real decorrido (calculado no servidor) — ou um QR novo, se já expirou. */
  const retomarQr = () => {
    if (document.querySelector("[data-conexoes-card] .card-cronometro")) atualizarCartao();
  };
  window.addEventListener("pageshow", (e) => { if (e.persisted) retomarQr(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    consultar();
    retomarQr();
  });
  /* Contagem regressiva do texto "expira em N segundos". O cartão é trocado
     inteiro por atualizarCartao(), então o relógio olha o elemento atual a cada
     segundo e calcula pelo horário de término (não perde tempo com a aba
     escondida): o N do servidor vira o instante em que o código expira. */
  const fins = new WeakMap();
  const tique = () => {
    const el = document.querySelector("[data-qr-restante]");
    if (!el) return;
    if (!fins.has(el)) fins.set(el, Date.now() + Number(el.dataset.qrRestante) * 1000);
    const restante = Math.max(0, Math.ceil((fins.get(el) - Date.now()) / 1000));
    const texto = el.closest("[data-qr-contagem]");
    if (restante === 0 && texto) {
      texto.textContent = "O código expirou. Gere um novo para conectar.";
      return;
    }
    el.textContent = restante;
    const unidade = texto && texto.querySelector("[data-qr-unidade]");
    if (unidade) unidade.textContent = restante === 1 ? "segundo" : "segundos";
  };
  window.setInterval(tique, 1000);
  tique();
  ciclo();
})();
