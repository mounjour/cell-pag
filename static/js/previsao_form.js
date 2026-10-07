/* Prévia somente leitura. Nunca envia anexos nem dispara o formulário de gravação. */
(function () {
  document.querySelectorAll('form[data-previsao-url]').forEach(function (form) {
    var destino = form.querySelector('[data-previsao-texto]');
    var card = document.querySelector('[data-previsao-card]');
    var timer, controller, versao = 0;
    function mostrarMensagem(texto) {
      card.classList.remove('carregando');
      var secao = document.createElement('section');
      secao.className = 'card resumo-cobranca';
      var titulo = document.createElement('h2');
      titulo.textContent = 'Resumo da cobrança';
      var p = document.createElement('p');
      p.className = 'resumo-vazio';
      p.textContent = texto;
      secao.append(titulo, p);
      card.replaceChildren(secao);
    }
    function mostrarCard(conteudo) {
      card.classList.remove('carregando');
      if (conteudo.html) card.innerHTML = conteudo.html; // HTML montado e escapado no servidor
      else mostrarMensagem(conteudo.texto);
    }
    async function atualizar(atual) {
      controller = new AbortController();
      var dados = new URLSearchParams();
      var campos = form.dataset.previsaoCampos ? form.dataset.previsaoCampos.split(',') :
        ['vencimento', 'data_pagamento', 'valor_pago', 'juros_pago', 'forma'];
      campos.forEach(function (nome) {
        if (form.elements[nome]) dados.set(nome, form.elements[nome].value);
      });
      try {
        var resposta = await fetch(form.dataset.previsaoUrl, {
          method: 'POST', credentials: 'same-origin', signal: controller.signal,
          headers: {'X-CSRFToken': form.elements.csrfmiddlewaretoken.value}, body: dados
        });
        if (!resposta.ok || resposta.redirected) throw new Error('Prévia indisponível');
        var conteudo = await resposta.json();
        if (atual === versao) {
          if (destino) destino.textContent = conteudo.texto;
          if (card) mostrarCard(conteudo);
        }
      } catch (erro) {
        if (erro.name !== 'AbortError' && atual === versao) {
          var aviso = 'Não foi possível atualizar a prévia. Confira os valores antes de salvar.';
          if (destino) destino.textContent = aviso;
          if (card) mostrarMensagem(aviso);
        }
      }
    }
    function agendar() {
      clearTimeout(timer);
      if (controller) controller.abort();
      var atual = ++versao;
      if (destino) destino.textContent = 'Atualizando prévia…';
      if (card) card.classList.add('carregando');
      timer = setTimeout(function () { atualizar(atual); }, 250);
    }
    form.addEventListener('input', agendar);
    form.addEventListener('change', agendar);
    agendar();
  });
})();
