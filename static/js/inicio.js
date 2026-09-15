/* Gráficos da tela inicial. Sem dependência de CDN — o Chart.js é servido
   localmente (static/js/chart.umd.min.js), então a CSP `script-src 'self'`
   continua fechada. Os dados entram por <script type="application/json">
   (django json_script); as cores saem das variáveis CSS, então seguem o tema
   claro/escuro que estiver ativo no carregamento. */
(function () {
  if (typeof Chart === "undefined") return;

  var css = getComputedStyle(document.documentElement);
  function v(nome, fallback) {
    return (css.getPropertyValue(nome) || fallback).trim();
  }
  function dados(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }
  function brl(n) {
    return "R$ " + Number(n).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  Chart.defaults.color = v("--ink-faint", "#71847d");
  Chart.defaults.borderColor = v("--line", "#dce4e1");
  Chart.defaults.font.family =
    "'Source Sans 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif";

  // O tooltip usa os mesmos tokens de "cartão" do resto da UI (superfície +
  // tinta + linha) — sempre legível nos dois temas, sem inverter cores.
  Chart.defaults.plugins.tooltip.backgroundColor = v("--surface", "#ffffff");
  Chart.defaults.plugins.tooltip.titleColor = v("--ink", "#17231f");
  Chart.defaults.plugins.tooltip.bodyColor = v("--ink-soft", "#4e5e58");
  Chart.defaults.plugins.tooltip.borderColor = v("--line-strong", "#b9c7c2");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.boxPadding = 4;

  var serie = dados("serie-data");
  if (serie) {
    new Chart(document.getElementById("grafico-meses"), {
      type: "bar",
      data: {
        labels: serie.labels,
        datasets: [
          {
            label: "Previsto",
            data: serie.previsto,
            backgroundColor: v("--accent", "#0d6b63") + "45",
            borderRadius: 4,
          },
          {
            label: "Recebido",
            data: serie.recebido,
            backgroundColor: v("--ok", "#1e8e3e"),
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ctx.dataset.label + ": " + brl(ctx.parsed.y);
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            beginAtZero: true,
            ticks: { callback: function (val) { return brl(val); } },
          },
        },
      },
    });
  }

  var status = dados("status-data");
  if (status) {
    new Chart(document.getElementById("grafico-status"), {
      type: "doughnut",
      data: {
        labels: status.labels,
        datasets: [
          {
            data: status.data,
            backgroundColor: [
              v("--ok", "#1e8e3e"),
              v("--amber", "#e8710a"),
              v("--critical", "#d93025"),
              v("--ink-faint", "#5f6368"),
            ],
            borderColor: v("--surface", "#ffffff"),
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: { legend: { position: "bottom" } },
      },
    });
  }
})();
