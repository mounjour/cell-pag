/* Dia de cobrança do contrato: mostra só os campos que valem para a frequência escolhida
   e sugere a data da primeira cobrança (continua editável). A conta é a mesma do servidor
   (apps/pagamentos/recorrencia.py: sugerir_primeira_cobranca); o servidor valida de novo. */
(function () {
  var form = document.querySelector('form[data-previsao-url]');
  if (!form || !form.elements.estrutura || !form.elements.primeira_cobranca) return;

  var el = form.elements;
  var grupos = {};
  form.querySelectorAll('[data-cobranca-grupo]').forEach(function (g) {
    grupos[g.dataset.cobrancaGrupo] = g;
  });

  function lerData(texto) {
    var p = (texto || '').split('-');
    return p.length === 3 ? new Date(+p[0], +p[1] - 1, +p[2]) : null;
  }
  function formatar(d) {
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var dia = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + dia;
  }
  function somarDias(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
  function ultimoDia(ano, mes) { return new Date(ano, mes + 1, 0).getDate(); }
  function diaNoMes(ano, mes, dia) {
    var base = new Date(ano, mes, 1);
    return new Date(base.getFullYear(), base.getMonth(), Math.min(dia, ultimoDia(base.getFullYear(), base.getMonth())));
  }
  function diaDaSemana(d) { return (d.getDay() + 6) % 7; } // 0 = segunda

  function modo() {
    var estrutura = el.estrutura.value;
    var diasDoMes = estrutura === 'quinzenal' && el.quinzena.value === 'dias_mes';
    return {
      estrutura: estrutura,
      semana: estrutura === 'semanal' || (estrutura === 'quinzenal' && !diasDoMes),
      mes: estrutura === 'mensal' || diasDoMes,
      doisDias: diasDoMes
    };
  }

  function mostrarGrupos() {
    var m = modo();
    if (grupos.quinzena) grupos.quinzena.hidden = m.estrutura !== 'quinzenal';
    if (grupos.semana) grupos.semana.hidden = !m.semana;
    if (grupos.mes) grupos.mes.hidden = !m.mes;
    if (grupos.mes2) grupos.mes2.hidden = !m.doisDias;
    var rotulo = form.querySelector('label[for="' + el.dia_mes.id + '"]');
    if (rotulo) rotulo.textContent = m.doisDias ? 'Primeiro dia do mês:' : 'Dia do mês da cobrança:';
  }

  function sugerir() {
    var compra = lerData(el.data_inicio.value);
    var m = modo();
    if (!compra || !m.estrutura) return '';
    if (m.semana) {
      if (el.dia_semana.value === '') return '';
      var marco = somarDias(compra, m.estrutura === 'semanal' ? 7 : 14);
      return formatar(somarDias(marco, (+el.dia_semana.value - diaDaSemana(marco) + 7) % 7));
    }
    var dias = [parseInt(el.dia_mes.value, 10)];
    if (m.doisDias) dias.push(parseInt(el.dia_mes_2.value, 10));
    if (dias.some(function (d) { return !(d >= 1 && d <= 31); })) return '';
    var ponto = m.doisDias ? somarDias(compra, 15) : diaNoMes(compra.getFullYear(), compra.getMonth() + 1, compra.getDate());
    for (var i = 0; i < 4; i++) {
      var candidatos = dias.map(function (d) { return diaNoMes(ponto.getFullYear(), ponto.getMonth() + i, d); })
        .filter(function (d) { return d >= ponto; })
        .sort(function (a, b) { return a - b; });
      if (candidatos.length) return formatar(candidatos[0]);
    }
    return '';
  }

  var manual = !!el.primeira_cobranca.value; // data já preenchida (edição / revisão): não sobrescreve

  function avisar() {
    el.primeira_cobranca.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function aoMudarEscolha() {
    mostrarGrupos();
    if (manual) return;
    var sugestao = sugerir();
    if (sugestao && sugestao !== el.primeira_cobranca.value) {
      el.primeira_cobranca.value = sugestao;
      avisar();
    }
  }

  function aoMudarFrequencia() {
    manual = false; // outra frequência invalida a data anterior
    el.primeira_cobranca.value = '';
    aoMudarEscolha();
  }

  function aoEditarData() {
    var d = lerData(el.primeira_cobranca.value);
    manual = !!d;
    if (!d) { aoMudarEscolha(); return; }
    var m = modo();
    if (m.semana) el.dia_semana.value = String(diaDaSemana(d));
    else if (el.dia_mes.value === '') el.dia_mes.value = d.getDate();
  }

  ['estrutura', 'quinzena'].forEach(function (nome) {
    if (el[nome]) el[nome].addEventListener('change', aoMudarFrequencia);
  });
  // Escolher outro dia refaz a sugestão; mudar só a data da compra respeita uma data já editada.
  function aoMudarDia() {
    manual = false;
    aoMudarEscolha();
  }
  ['dia_semana', 'dia_mes', 'dia_mes_2'].forEach(function (nome) {
    if (!el[nome]) return;
    el[nome].addEventListener('change', aoMudarDia);
    el[nome].addEventListener('input', aoMudarDia);
  });
  ['data_inicio'].forEach(function (nome) {
    el[nome].addEventListener('change', aoMudarEscolha);
    el[nome].addEventListener('input', aoMudarEscolha);
  });
  el.primeira_cobranca.addEventListener('input', aoEditarData);
  el.primeira_cobranca.addEventListener('change', function (evento) {
    if (evento.isTrusted) aoEditarData();
  });

  mostrarGrupos();
  if (!manual) aoMudarEscolha();
})();
