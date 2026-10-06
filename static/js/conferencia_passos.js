/* Conferência do cadastro em passos (Cliente → Aparelho → Valores → Resumo).
   Tudo na mesma página: nada é enviado até o último passo. Sem JS, todos os
   blocos aparecem de uma vez, como antes. */
(() => {
  const raiz = document.querySelector("[data-passos]");
  if (!raiz) return;
  const paineis = [...raiz.querySelectorAll(".passo")];
  if (paineis.length < 2) return;

  const trilha = raiz.querySelector("[data-passos-trilha]");
  const btnVoltar = raiz.querySelector("[data-passos-voltar]");
  const btnProximo = raiz.querySelector("[data-passos-proximo]");
  const btnConfirmar = raiz.querySelector("[data-passos-confirmar]");
  const total = paineis.length;

  let atual = Math.min(Math.max(parseInt(raiz.dataset.passoInicial, 10) || 1, 1), total) - 1;
  let maior = atual; // até onde já chegou: não dá para pular a leitura de um passo

  const aviso = document.createElement("p");
  aviso.className = "sr-only";
  aviso.setAttribute("aria-live", "polite");
  raiz.insertBefore(aviso, trilha);

  const itens = paineis.map((painel, i) => {
    const li = document.createElement("li");
    const botao = document.createElement("button");
    botao.type = "button";
    botao.innerHTML = '<span class="n"></span><span class="t"></span>';
    botao.querySelector(".n").textContent = String(i + 1);
    botao.querySelector(".t").textContent = painel.dataset.passoTitulo;
    botao.addEventListener("click", () => { if (i <= maior) mostrar(i, true); });
    li.append(botao);
    trilha.append(li);
    return botao;
  });

  // Reinicia a animação CSS do elemento (tirar a classe, forçar o layout, pôr de novo).
  function animar(el, classe) {
    el.classList.remove("anima-frente", "anima-tras", "anima-destaque");
    void el.offsetWidth;
    el.classList.add(classe);
  }

  function mostrar(i, mover) {
    const anterior = atual;
    atual = i;
    maior = Math.max(maior, i);
    paineis.forEach((painel, n) => { painel.hidden = n !== i; });
    itens.forEach((botao, n) => {
      botao.parentElement.classList.toggle("feito", n < i);
      botao.parentElement.classList.toggle("atual", n === i);
      botao.disabled = n > maior;
      if (n === i) botao.setAttribute("aria-current", "step"); else botao.removeAttribute("aria-current");
    });
    btnVoltar.hidden = i === 0;
    btnProximo.hidden = i === total - 1;
    if (btnConfirmar) btnConfirmar.hidden = i !== total - 1;
    aviso.textContent = `Passo ${i + 1} de ${total}: ${paineis[i].dataset.passoTitulo}`;
    if (mover && i !== anterior) {
      animar(paineis[i], i > anterior ? "anima-frente" : "anima-tras");
      const caixa = paineis[i].querySelector(".confirmacao-responsabilidade");
      if (caixa) animar(caixa, "anima-destaque"); // chama a atenção ao chegar no aceite
    }
    if (mover) {
      const titulo = paineis[i].querySelector("h2");
      if (titulo) { titulo.tabIndex = -1; titulo.focus({ preventScroll: true }); }
      trilha.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  btnVoltar.addEventListener("click", () => mostrar(Math.max(0, atual - 1), true));
  btnProximo.addEventListener("click", () => mostrar(Math.min(total - 1, atual + 1), true));

  raiz.classList.add("passos-ativos");
  trilha.hidden = false;
  mostrar(atual, false);
})();
