/* Prévia somente leitura. Nunca envia anexos nem dispara o formulário de gravação. */
(function () {
  document.querySelectorAll('form[data-previsao-url]').forEach(function (form) {
    var destino = form.querySelector('[data-previsao-texto]');
    var timer, controller, versao = 0;
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
        if (atual === versao) destino.textContent = conteudo.texto;
      } catch (erro) {
        if (erro.name !== 'AbortError' && atual === versao)
          destino.textContent = 'Não foi possível atualizar a prévia. Confira os valores antes de salvar.';
      }
    }
    function agendar() {
      clearTimeout(timer);
      if (controller) controller.abort();
      var atual = ++versao;
      destino.textContent = 'Atualizando prévia…';
      timer = setTimeout(function () { atualizar(atual); }, 250);
    }
    form.addEventListener('input', agendar);
    form.addEventListener('change', agendar);
    agendar();
  });
})();
