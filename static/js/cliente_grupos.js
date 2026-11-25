(() => {
  const painel = document.querySelector('[data-grupos-url]');
  if (!painel) return;
  const campo = document.getElementById('id_grupo_whatsapp');
  const seletor = document.getElementById('grupo_whatsapp_selecao');
  const status = document.getElementById('grupos-status');
  const tentar = painel.querySelector('[data-grupos-tentar]');
  const token = document.getElementById('id_grupo_whatsapp_token');
  let tokens = new Map();
  painel.querySelector('[data-grupos-selecao]').hidden = false;
  // O campo original continua sendo enviado, inclusive durante a carga e sem JS.
  campo.labels[0].textContent = 'Ou cole o identificador do grupo';
  seletor.addEventListener('change', () => {
    campo.value = seletor.value;
    token.value = tokens.get(campo.value) || '';
  });
  campo.addEventListener('input', () => {
    seletor.value = campo.value;
    token.value = tokens.get(campo.value) || '';
  });

  async function carregar() {
    tentar.hidden = true;
    seletor.disabled = true;
    seletor.setAttribute('aria-busy', 'true');
    status.textContent = 'Carregando grupos… Você pode preencher os outros dados enquanto aguarda.';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 55000);
    try {
      const resposta = await fetch(painel.dataset.gruposUrl, {
        signal: controller.signal, headers: { Accept: 'application/json' },
      });
      if (!resposta.ok) throw new Error('Falha ao carregar');
      const dados = await resposta.json();
      if (!Array.isArray(dados.grupos)) throw new Error('Lista inválida');
      const atual = campo.value.trim();
      tokens = new Map(dados.grupos.map(g => [g.id, g.token]));
      token.value = tokens.get(atual) || token.value;
      seletor.replaceChildren(new Option('Sem grupo: usar o telefone do cliente', ''));
      dados.grupos.forEach(g => seletor.add(new Option(`${g.nome} (${g.participantes} participantes)`, g.id)));
      if (atual && !dados.grupos.some(g => g.id === atual)) {
        seletor.add(new Option(painel.dataset.grupoNome || atual, atual));
      }
      seletor.value = atual;
      seletor.disabled = false;
      status.textContent = dados.grupos.length ? 'Grupos carregados. Escolha um grupo na lista.' : 'Nenhum grupo encontrado. Você pode informar o identificador abaixo ou tentar novamente.';
      tentar.hidden = dados.grupos.length > 0;
    } catch (_) {
      status.textContent = 'Não foi possível carregar os grupos. Tente novamente ou cole o identificador abaixo (termina em @g.us). Seus dados foram mantidos.';
      tentar.hidden = false;
    } finally {
      clearTimeout(timer);
      seletor.removeAttribute('aria-busy');
    }
  }
  tentar.addEventListener('click', carregar);
  carregar();
})();
