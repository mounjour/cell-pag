/* Bloqueios: as abas mostram uma lista por vez. Abre na primeira que tem alguém esperando ação. */
(() => {
  const abas = document.querySelector("[data-blq-abas]");
  if (!abas) return;
  const botoes = [...abas.querySelectorAll("[data-alvo]")];
  const paineis = [...document.querySelectorAll("[data-painel]")];
  document.documentElement.classList.add("blq-com-abas");

  // Fundo azul único que desliza até a aba escolhida.
  const fundo = document.createElement("span");
  fundo.className = "blq-indicador";
  fundo.setAttribute("aria-hidden", "true");
  abas.prepend(fundo);
  const moverFundo = (botao, animar) => {
    if (!animar) fundo.classList.add("sem-transicao");
    fundo.style.width = botao.offsetWidth + "px";
    fundo.style.height = botao.offsetHeight + "px";
    fundo.style.transform = `translate(${botao.offsetLeft}px, ${botao.offsetTop}px)`;
    if (!animar) { void fundo.offsetWidth; fundo.classList.remove("sem-transicao"); }
  };
  let primeira = true;

  const abrir = (alvo, foco) => {
    botoes.forEach((b) => {
      const ativo = b.dataset.alvo === alvo;
      b.setAttribute("aria-selected", String(ativo));
      b.tabIndex = ativo ? 0 : -1;
      if (ativo && foco) b.focus();
      if (ativo) moverFundo(b, !primeira);
    });
    primeira = false;
    paineis.forEach((p) => { p.hidden = p.dataset.painel !== alvo; });
    try { sessionStorage.setItem("blqAba", alvo); } catch (e) { /* sem armazenamento: só não lembra a aba */ }
  };

  botoes.forEach((b, i) => {
    b.addEventListener("click", () => abrir(b.dataset.alvo));
    b.addEventListener("keydown", (ev) => {
      const passo = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (!passo) return;
      ev.preventDefault();
      abrir(botoes[(i + passo + botoes.length) % botoes.length].dataset.alvo, true);
    });
  });

  // Prioridade: quem espera bloqueio, depois quem espera liberação; senão volta à última aba vista.
  const comGente = ["bloquear", "desbloquear"].find((n) => Number((paineis.find((p) => p.dataset.painel === n) || {}).dataset?.qtd || 0) > 0);
  let lembrada = null;
  try { lembrada = sessionStorage.getItem("blqAba"); } catch (e) { /* idem */ }
  const valida = (n) => n && botoes.some((b) => b.dataset.alvo === n);
  abrir(comGente || (valida(lembrada) ? lembrada : "bloquear"));
  window.addEventListener("resize", () => {
    const ativo = botoes.find((b) => b.getAttribute("aria-selected") === "true");
    if (ativo) moverFundo(ativo, false);
  });
})();
