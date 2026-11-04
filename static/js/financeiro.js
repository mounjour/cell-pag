/* Gráficos do dashboard financeiro. Chart.js servido localmente (CSP script-src 'self'); os dados entram por
   <script type="application/json"> (json_script) e as cores saem das variáveis CSS, então seguem o tema. */
(function () {
  if (typeof Chart === "undefined") return;

  var css = getComputedStyle(document.documentElement);
  function v(nome, fallback) { return (css.getPropertyValue(nome) || fallback).trim(); }
  function dados(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }
  function brl(n) {
    return "R$ " + Number(n).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function curto(n) {
    return n >= 1000 ? "R$ " + (n / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil" : "R$ " + n;
  }

  Chart.defaults.color = v("--ink-faint", "#6b7280");
  Chart.defaults.borderColor = v("--line", "#e5e7eb");
  Chart.defaults.font.family = "'DM Sans', system-ui, -apple-system, 'Segoe UI', Arial, sans-serif";
  var tip = Chart.defaults.plugins.tooltip;
  tip.backgroundColor = v("--surface", "#ffffff");
  tip.titleColor = v("--ink", "#111827");
  tip.bodyColor = v("--ink-soft", "#4b5563");
  tip.borderColor = v("--line-strong", "#d1d5db");
  tip.borderWidth = 1;
  tip.padding = 10;
  tip.cornerRadius = 8;

  var opcoesBase = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } },
      tooltip: { callbacks: { label: function (c) { return c.dataset.label + ": " + brl(c.parsed.y); } } },
    },
    scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { callback: curto } } },
  };

  var entradas = dados("fin-entradas-data");
  var elEntradas = document.getElementById("fin-entradas");
  if (entradas && elEntradas) {
    var opcoes = JSON.parse(JSON.stringify(opcoesBase));
    opcoes.plugins.tooltip = {
      callbacks: {
        label: function (c) { return c.dataset.label + ": " + brl(c.parsed.y); },
        footer: function (itens) {
          var t = itens.reduce(function (s, i) { return s + i.parsed.y; }, 0);
          return "Total: " + brl(t);
        },
      },
    };
    opcoes.scales.x.stacked = true;
    opcoes.scales.y.stacked = true;
    opcoes.scales.x.ticks = { maxTicksLimit: 12, autoSkip: true };
    new Chart(elEntradas, {
      type: "bar",
      data: {
        labels: entradas.labels,
        datasets: [
          { label: "Parcelas", data: entradas.parcelas, backgroundColor: v("--money", "#12a150"), borderRadius: 3 },
          { label: "Juros", data: entradas.juros, backgroundColor: v("--ink-faint", "#6b7280"), borderRadius: 3 },
        ],
      },
      options: opcoes,
    });
  }

  var meses = dados("fin-meses-data");
  var elMeses = document.getElementById("fin-meses");
  if (meses && elMeses) {
    new Chart(elMeses, {
      type: "bar",
      data: {
        labels: meses.labels,
        datasets: [
          { label: "Previsto", data: meses.previsto, backgroundColor: v("--line-strong", "#d1d5db"), borderRadius: 3 },
          { label: "Recebido", data: meses.recebido, backgroundColor: v("--money", "#12a150"), borderRadius: 3 },
        ],
      },
      options: opcoesBase,
    });
  }

  var proximos = dados("fin-proximos-data");
  var elProximos = document.getElementById("fin-proximos");
  if (proximos && elProximos && proximos.labels.length) {
    var opcoesProx = JSON.parse(JSON.stringify(opcoesBase));
    opcoesProx.plugins.legend = { display: false };
    opcoesProx.plugins.tooltip = { callbacks: { label: function (c) { return brl(c.parsed.y); } } };
    new Chart(elProximos, {
      type: "bar",
      data: { labels: proximos.labels, datasets: [{ label: "A vencer", data: proximos.valores, backgroundColor: v("--ink-soft", "#4b5563"), borderRadius: 3 }] },
      options: opcoesProx,
    });
  }
})();
