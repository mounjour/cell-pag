/* Ajuda: a busca filtra as perguntas e o assunto visível fica marcado no índice. */
(() => {
  const campo = document.querySelector("[data-ajuda-busca]");
  const secoes = [...document.querySelectorAll("[data-ajuda-secao]")];
  const nada = document.querySelector("[data-ajuda-nada]");
  const indice = [...document.querySelectorAll(".ajd-indice a")];
  const normal = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // Guarda o texto original de cada pergunta para poder marcar e desmarcar o termo procurado.
  const itens = [...document.querySelectorAll("[data-ajuda-item]")];
  itens.forEach((i) => { i.dataset.original = i.innerHTML; i.dataset.texto = normal(i.textContent); });

  const marcar = (item, termo) => {
    item.innerHTML = item.dataset.original;
    if (!termo) return;
    const caminhar = document.createTreeWalker(item, NodeFilter.SHOW_TEXT);
    const nos = [];
    while (caminhar.nextNode()) nos.push(caminhar.currentNode);
    nos.forEach((no) => {
      const i = normal(no.nodeValue).indexOf(termo);
      if (i < 0) return;
      const meio = no.splitText(i);
      meio.splitText(termo.length);
      const m = document.createElement("mark");
      meio.parentNode.replaceChild(m, meio);
      m.appendChild(meio);
    });
  };

  const filtrar = () => {
    const termo = normal(campo.value.trim());
    let algum = false;
    secoes.forEach((s) => {
      const titulo = normal(s.querySelector(".ajd-secao-topo").textContent);
      const tituloBate = termo && titulo.includes(termo);
      let visiveis = 0;
      s.querySelectorAll("[data-ajuda-item]").forEach((i) => {
        const bate = !termo || tituloBate || i.dataset.texto.includes(termo);
        i.hidden = !bate;
        marcar(i, bate ? termo : "");
        if (bate) visiveis += 1;
      });
      s.hidden = visiveis === 0;
      const link = indice.find((a) => a.getAttribute("href") === "#" + s.id);
      if (link) link.hidden = s.hidden;
      if (!s.hidden) algum = true;
    });
    nada.hidden = algum;
  };
  if (campo) campo.addEventListener("input", filtrar);

  // No computador só a coluna das perguntas rola: o índice leva até o assunto dentro dela.
  const coluna = document.querySelector(".ajd-conteudo");
  const colunaRola = () => coluna && getComputedStyle(coluna).overflowY === "auto";
  const marcarAtivo = (id) => indice.forEach((a) => a.classList.toggle("ativo", a.getAttribute("href") === "#" + id));
  const irPara = (id, suave) => {
    const alvo = document.getElementById(id);
    if (!alvo) return;
    if (colunaRola()) {
      coluna.scrollTo({ top: alvo.offsetTop, behavior: suave ? "smooth" : "auto" });
    } else {
      alvo.scrollIntoView({ behavior: suave ? "smooth" : "auto" });
    }
    marcarAtivo(id);
  };
  indice.forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    const id = a.getAttribute("href").slice(1);
    history.replaceState(null, "", "#" + id);
    irPara(id, !matchMedia("(prefers-reduced-motion: reduce)").matches);
  }));

  // Marca no índice o assunto que está na tela.
  if ("IntersectionObserver" in window) {
    const obs = new IntersectionObserver((entradas) => {
      const visivel = entradas.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visivel) marcarAtivo(visivel.target.id);
    }, { root: colunaRola() ? coluna : null, rootMargin: "0px 0px -70% 0px" });
    secoes.forEach((s) => obs.observe(s));
  }
  if (location.hash) irPara(location.hash.slice(1), false);
})();
