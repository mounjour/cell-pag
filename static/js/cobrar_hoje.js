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

  // O htmx, por padrão, ignora o corpo de respostas 4xx (não troca nada no
  // DOM) — sem isso, um formulário inválido devolve 422 com o HTML dos erros
  // pronto, mas a tela fica parada, sem mostrar nada (bug real: qualquer erro
  // de validação nesse diálogo ficava invisível). Força a troca mesmo em
  // erro só pra este formulário, pra exibir a mensagem devolvida pela view.
  document.body.addEventListener("htmx:beforeSwap", function (e) {
    var elt = e.detail.elt;
    if (elt && elt.id === "dialog-registrar-corpo" && e.detail.xhr.status === 422) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
    }
  });

  // Fecha o diálogo só quando a baixa do formulário foi de fato aceita
  // (POST com 2xx de verdade). Confere o status HTTP diretamente em vez de
  // `e.detail.successful` — o `isError = false` do beforeSwap acima existe só
  // pra liberar a troca de conteúdo em erro, mas também mudaria o valor de
  // `successful`, o que fecharia o diálogo mesmo com o formulário inválido.
  document.body.addEventListener("htmx:afterRequest", function (e) {
    var verb = e.detail.requestConfig && e.detail.requestConfig.verb;
    var elt = e.detail.elt;
    var status = e.detail.xhr && e.detail.xhr.status;
    var deuCerto = status >= 200 && status < 300;
    if (deuCerto && verb === "post" && elt && elt.id === "dialog-registrar-corpo") {
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
