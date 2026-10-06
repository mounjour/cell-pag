/* Máscaras de digitação: CPF (000.000.000-00) e telefone ((83) 99999-0000).
   Marque o campo com data-mascara="cpf" ou data-mascara="telefone". O servidor
   continua aceitando só números, com ou sem pontuação; isto é só para o operador
   ver o valor "do jeitinho certo" enquanto digita (e ao editar um cadastro). */
(() => {
  const soDigitos = (texto) => texto.replace(/\D/g, "");

  const cpf = (d) => {
    d = d.slice(0, 11);
    if (d.length <= 3) return d;
    if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`;
    if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`;
    return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
  };

  const telefone = (d) => {
    // Valor vindo do banco (+5583...): tira o 55 do país para exibir só DDD + número.
    if (d.length > 11 && d.startsWith("55")) d = d.slice(2);
    d = d.slice(0, 11);
    if (d.length === 0) return "";
    if (d.length <= 2) return `(${d}`;
    if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
    if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  };

  const FORMATADORES = { cpf, telefone };

  const formatar = (campo) => {
    const formatador = FORMATADORES[campo.dataset.mascara];
    if (!formatador) return;
    const posicao = campo.selectionStart;
    const digitosAntes = soDigitos((campo.value || "").slice(0, posicao ?? 0)).length;
    const novo = formatador(soDigitos(campo.value || ""));
    if (novo === campo.value) return;
    campo.value = novo;
    if (posicao === null || document.activeElement !== campo) return;
    // Mantém o cursor depois do mesmo número de dígitos de antes.
    let contados = 0, lugar = 0;
    while (lugar < novo.length && contados < digitosAntes) {
      if (/\d/.test(novo[lugar])) contados++;
      lugar++;
    }
    campo.setSelectionRange(lugar, lugar);
  };

  document.addEventListener("input", (evento) => {
    if (evento.target instanceof HTMLInputElement && evento.target.dataset.mascara) formatar(evento.target);
  });
  for (const campo of document.querySelectorAll("input[data-mascara]")) formatar(campo);
})();
