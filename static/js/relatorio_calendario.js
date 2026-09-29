// Seletor de período do relatório: atalhos + calendário de intervalo.
// Sempre envia periodo=personalizado com inicio/fim (AAAA-MM-DD).
(function () {
  var form = document.getElementById("filtro-periodo");
  if (!form) return;

  var botao = document.getElementById("periodo-botao");
  var rotulo = document.getElementById("periodo-rotulo");
  var pop = document.getElementById("periodo-pop");
  var atalhosEl = document.getElementById("periodo-atalhos");
  var mesesEl = document.getElementById("periodo-meses");
  var campoInicio = document.getElementById("id_inicio");
  var campoFim = document.getElementById("id_fim");
  var inputDe = document.getElementById("periodo-de");
  var inputAte = document.getElementById("periodo-ate");

  var MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  var DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

  function hoje() {
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  function soma(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
  function iso(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
  }
  function doIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }
  function br(d) {
    return String(d.getDate()).padStart(2, "0") + "/" +
      String(d.getMonth() + 1).padStart(2, "0") + "/" + d.getFullYear();
  }
  function mesmoDia(a, b) { return a && b && iso(a) === iso(b); }
  function segunda(d) { return soma(d, -((d.getDay() + 6) % 7)); }

  var ATALHOS = [
    ["hoje", "Hoje", function (h) { return [h, h]; }],
    ["ontem", "Ontem", function (h) { return [soma(h, -1), soma(h, -1)]; }],
    ["hoje_ontem", "Hoje e ontem", function (h) { return [soma(h, -1), h]; }],
    ["7", "Últimos 7 dias", function (h) { return [soma(h, -6), h]; }],
    ["14", "Últimos 14 dias", function (h) { return [soma(h, -13), h]; }],
    ["28", "Últimos 28 dias", function (h) { return [soma(h, -27), h]; }],
    ["30", "Últimos 30 dias", function (h) { return [soma(h, -29), h]; }],
    ["semana", "Esta semana", function (h) { return [segunda(h), h]; }],
    ["semana_passada", "Semana passada", function (h) {
      var s = soma(segunda(h), -7); return [s, soma(s, 6)];
    }],
    ["mes", "Este mês", function (h) {
      return [new Date(h.getFullYear(), h.getMonth(), 1), h];
    }],
    ["mes_passado", "Mês passado", function (h) {
      return [new Date(h.getFullYear(), h.getMonth() - 1, 1),
        new Date(h.getFullYear(), h.getMonth(), 0)];
    }],
    ["personalizado", "Personalizado", null]
  ];

  var aplicado = { ini: null, fim: null };   // o que está no relatório agora
  var ini = null, fim = null;                // seleção em andamento
  var aguardandoFim = false;
  var mesEsq = null;                         // 1º dia do mês da esquerda

  function atalhoDe(a, b) {
    var h = hoje();
    for (var i = 0; i < ATALHOS.length; i++) {
      if (!ATALHOS[i][2]) continue;
      var r = ATALHOS[i][2](h);
      if (mesmoDia(r[0], a) && mesmoDia(r[1], b)) return ATALHOS[i][0];
    }
    return "personalizado";
  }

  function atualizarRotulo() {
    var a = aplicado.ini, b = aplicado.fim;
    var chave = atalhoDe(a, b);
    var nome = "";
    ATALHOS.forEach(function (x) { if (x[0] === chave && chave !== "personalizado") nome = x[1] + ": "; });
    rotulo.textContent = nome + (mesmoDia(a, b) ? br(a) : br(a) + " – " + br(b));
  }

  function desenharAtalhos() {
    var ativo = ini && fim ? atalhoDe(ini, fim) : "personalizado";
    atalhosEl.innerHTML = "";
    ATALHOS.forEach(function (x) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "periodo-atalho";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", x[0] === ativo ? "true" : "false");
      b.dataset.chave = x[0];
      b.innerHTML = '<span class="periodo-radio"></span>' + x[1];
      atalhosEl.appendChild(b);
    });
  }

  function desenharMes(primeiro) {
    var ano = primeiro.getFullYear(), mes = primeiro.getMonth();
    var box = document.createElement("div");
    box.className = "periodo-mes";
    var t = document.createElement("div");
    t.className = "periodo-mes-titulo";
    t.textContent = MESES[mes] + " " + ano;
    box.appendChild(t);
    var grade = document.createElement("div");
    grade.className = "periodo-grade";
    DIAS.forEach(function (d) {
      var c = document.createElement("span");
      c.className = "periodo-dow";
      c.textContent = d;
      grade.appendChild(c);
    });
    var vazios = (primeiro.getDay() + 6) % 7;
    for (var i = 0; i < vazios; i++) grade.appendChild(document.createElement("span"));
    var total = new Date(ano, mes + 1, 0).getDate();
    var h = hoje();
    for (var dia = 1; dia <= total; dia++) {
      var d = new Date(ano, mes, dia);
      var b = document.createElement("button");
      b.type = "button";
      b.className = "periodo-dia";
      b.textContent = dia;
      b.dataset.iso = iso(d);
      b.setAttribute("aria-label", br(d));
      if (mesmoDia(d, h)) b.classList.add("hoje");
      if (d.getDay() === 0 || d.getDay() === 6) b.classList.add("fds");
      if (d.getDay() === 1 || dia === 1) b.classList.add("ini-semana");
      if (d.getDay() === 0 || dia === total) b.classList.add("fim-semana");
      if (ini && fim && d >= ini && d <= fim) b.classList.add("no-periodo");
      if (mesmoDia(d, ini)) b.classList.add("ponta", "ponta-ini");
      if (mesmoDia(d, fim)) b.classList.add("ponta", "ponta-fim");
      grade.appendChild(b);
    }
    box.appendChild(grade);
    return box;
  }

  function desenhar() {
    mesesEl.innerHTML = "";
    mesesEl.appendChild(desenharMes(mesEsq));
    mesesEl.appendChild(desenharMes(new Date(mesEsq.getFullYear(), mesEsq.getMonth() + 1, 1)));
    desenharAtalhos();
    var res = document.getElementById("periodo-resumo");
    if (ini && fim) {
      var n = Math.round((fim - ini) / 86400000) + 1;
      res.innerHTML = "<strong>" + n + (n === 1 ? " dia" : " dias") + "</strong> · " +
        (n === 1 ? br(ini) : br(ini) + " – " + br(fim)) +
        (aguardandoFim ? " · escolha o último dia" : "");
    } else {
      res.textContent = "";
    }
    inputDe.value = ini ? iso(ini) : "";
    inputAte.value = fim ? iso(fim) : "";
  }

  function definir(a, b) {
    ini = a; fim = b; aguardandoFim = false;
    mesEsq = new Date(a.getFullYear(), a.getMonth(), 1);
    desenhar();
  }

  function abrir() {
    ini = aplicado.ini; fim = aplicado.fim; aguardandoFim = false;
    // Um mês só, sempre — o do fim do período atual (as setas navegam pros outros).
    mesEsq = new Date(fim.getFullYear(), fim.getMonth(), 1);
    desenhar();
    pop.hidden = false;
    botao.setAttribute("aria-expanded", "true");
  }
  function fechar() {
    pop.hidden = true;
    botao.setAttribute("aria-expanded", "false");
  }

  botao.addEventListener("click", function () { pop.hidden ? abrir() : fechar(); });
  document.getElementById("periodo-cancelar").addEventListener("click", function () {
    fechar(); botao.focus();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !pop.hidden) { fechar(); botao.focus(); }
  });
  document.addEventListener("click", function (e) {
    // O calendário é redesenhado a cada clique: alvo já removido do DOM não é "fora".
    if (!e.target.isConnected) return;
    if (!pop.hidden && !form.contains(e.target)) fechar();
  });

  document.getElementById("periodo-ant").addEventListener("click", function () {
    mesEsq = new Date(mesEsq.getFullYear(), mesEsq.getMonth() - 1, 1); desenhar();
  });
  document.getElementById("periodo-prox").addEventListener("click", function () {
    mesEsq = new Date(mesEsq.getFullYear(), mesEsq.getMonth() + 1, 1); desenhar();
  });

  atalhosEl.addEventListener("click", function (e) {
    var b = e.target.closest(".periodo-atalho");
    if (!b) return;
    var achado = ATALHOS.filter(function (x) { return x[0] === b.dataset.chave; })[0];
    if (achado[2]) {
      var r = achado[2](hoje());
      definir(r[0], r[1]);
    } else {
      aguardandoFim = false;
      atalhosEl.querySelectorAll(".periodo-atalho").forEach(function (x) {
        x.setAttribute("aria-checked", x === b ? "true" : "false");
      });
    }
  });

  mesesEl.addEventListener("click", function (e) {
    var b = e.target.closest(".periodo-dia");
    if (!b) return;
    var d = doIso(b.dataset.iso);
    if (!aguardandoFim) {
      ini = d; fim = d; aguardandoFim = true;
    } else {
      if (d < ini) { fim = ini; ini = d; } else { fim = d; }
      aguardandoFim = false;
    }
    desenhar();
  });

  mesesEl.addEventListener("mouseover", function (e) {
    if (!aguardandoFim) return;
    var b = e.target.closest(".periodo-dia");
    if (!b) return;
    var d = doIso(b.dataset.iso);
    var a = d < ini ? d : ini, z = d < ini ? ini : d;
    mesesEl.querySelectorAll(".periodo-dia").forEach(function (x) {
      var v = doIso(x.dataset.iso);
      x.classList.toggle("previa", v >= a && v <= z);
    });
  });

  function daCaixa() {
    var a = doIso(inputDe.value), b = doIso(inputAte.value);
    if (!a || !b) return;
    if (b < a) { var t = a; a = b; b = t; }
    definir(a, b);
  }
  inputDe.addEventListener("change", daCaixa);
  inputAte.addEventListener("change", daCaixa);

  form.addEventListener("submit", function (e) {
    if (!ini || !fim) { e.preventDefault(); return; }
    campoInicio.value = iso(ini);
    campoFim.value = iso(fim);
  });

  // Estado inicial: o período que o servidor está mostrando (ou hoje).
  var h0 = hoje();
  aplicado.ini = doIso(form.dataset.inicio) || h0;
  aplicado.fim = doIso(form.dataset.fim) || aplicado.ini;
  campoInicio.value = iso(aplicado.ini);
  campoFim.value = iso(aplicado.fim);
  atualizarRotulo();
})();
