/* Abas que são links (cada uma abre outra página): o fundo azul desliza até a aba clicada
   e, na página seguinte, parte de onde estava. Uso: <nav data-segmentos="nome"> com links e a ativa com .ativo. */
(() => {
  document.querySelectorAll("[data-segmentos]").forEach((grupo) => {
    const chave = "segmentos:" + grupo.dataset.segmentos;
    const fundo = document.createElement("span");
    fundo.className = "segmentos-fundo";
    fundo.setAttribute("aria-hidden", "true");
    grupo.prepend(fundo);
    grupo.classList.add("segmentos-pronto");

    const medir = (el) => ({ x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
    const pintar = (m, animar) => {
      if (!animar) fundo.classList.add("sem-transicao");
      fundo.style.width = m.w + "px";
      fundo.style.height = m.h + "px";
      fundo.style.transform = `translate(${m.x}px, ${m.y}px)`;
      if (!animar) { void fundo.offsetWidth; fundo.classList.remove("sem-transicao"); }
    };
    const guardar = (m) => { try { sessionStorage.setItem(chave, JSON.stringify(m)); } catch (e) { /* sem armazenamento: só não desliza entre páginas */ } };

    const ativo = grupo.querySelector(".ativo");
    if (!ativo) return;
    const destino = medir(ativo);
    let antes = null;
    try { antes = JSON.parse(sessionStorage.getItem(chave) || "null"); } catch (e) { /* idem */ }
    if (antes && (antes.x !== destino.x || antes.w !== destino.w)) {
      pintar(antes, false);
      pintar(destino, true);
    } else {
      pintar(destino, false);
    }
    guardar(destino);

    grupo.addEventListener("click", (ev) => {
      const link = ev.target.closest("a");
      if (!link || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
      const m = medir(link);
      grupo.querySelectorAll("a").forEach((a) => a.classList.toggle("ativo", a === link));
      pintar(m, true);
      guardar(m);
    });
    window.addEventListener("resize", () => {
      const atual = grupo.querySelector(".ativo");
      if (atual) pintar(medir(atual), false);
    });
    // A fonte pode terminar de carregar depois: aí a largura das abas muda e o fundo acompanha.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        const atual = grupo.querySelector(".ativo");
        if (atual) { const m = medir(atual); pintar(m, true); guardar(m); }
      });
    }
  });
})();
