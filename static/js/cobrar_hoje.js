// Painel "Cobrar hoje": diálogo de registrar pagamento, aberto/fechado via
// htmx sem recarregar a página. Delegado em document.body (não em cada botão
// ou no <form>) porque o conteúdo do diálogo é trocado pelo htmx a cada
// abertura — e o próprio <form> some do DOM assim que a baixa é aceita
// (o alvo da troca é o container que o envolve), então um listener preso a
// ele nunca veria o evento de sucesso.
document.addEventListener("DOMContentLoaded", function () {
  var dialog = document.getElementById("dialog-registrar");
  var corpo = document.getElementById("dialog-registrar-corpo");
  if (!dialog || !corpo) return;

  // Abre o diálogo assim que a requisição do link "Registrar" começa — não
  // espera o conteúdo chegar, pra não dar sensação de travamento no clique.
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var gatilho = e.target.closest && e.target.closest("[data-abre-dialog]");
    if (!gatilho) return;
    var alvo = document.getElementById(gatilho.dataset.abreDialog);
    if (alvo) alvo.showModal();
  });

  // Fecha o diálogo só quando a baixa do formulário foi de fato aceita
  // (POST com 2xx). Em caso de formulário inválido a view devolve 422 —
  // `successful` fica falso e o diálogo continua aberto mostrando os erros.
  document.body.addEventListener("htmx:afterRequest", function (e) {
    var verb = e.detail.requestConfig && e.detail.requestConfig.verb;
    var elt = e.detail.elt;
    if (e.detail.successful && verb === "post" && elt && elt.id === "dialog-registrar-corpo") {
      dialog.close();
    }
  });

  // Fechar pelo botão "Cancelar"/"Fechar" (delegado — o conteúdo do diálogo
  // é trocado pelo htmx) ou clicando fora dele (a <dialog> nativa não faz
  // isso sozinha).
  document.body.addEventListener("click", function (e) {
    if (e.target.closest("[data-fechar-dialog]")) dialog.close();
  });

  dialog.addEventListener("click", function (e) {
    var r = dialog.getBoundingClientRect();
    var dentro =
      e.clientX >= r.left && e.clientX <= r.right &&
      e.clientY >= r.top && e.clientY <= r.bottom;
    if (!dentro) dialog.close();
  });
});
