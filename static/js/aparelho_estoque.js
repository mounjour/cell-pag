/* Ao escolher um aparelho do estoque no formulário de contrato, preenche
   modelo/IMEI sozinho — o texto da <option> já vem como "modelo · IMEI xxx"
   (Aparelho.__str__), então não precisa de dado extra vindo do servidor. */
(function () {
  var select = document.querySelector("[data-preenche-aparelho]");
  if (!select) return;
  var modelo = document.getElementById("id_aparelho_modelo");
  var imei = document.getElementById("id_imei");
  if (!modelo || !imei) return;

  select.addEventListener("change", function () {
    var opcao = select.options[select.selectedIndex];
    if (!opcao || !opcao.value) return; // "-- nenhum --": não mexe no que já tinha
    var texto = opcao.textContent || "";
    var partes = texto.split(" · IMEI ");
    modelo.value = partes[0].trim();
    imei.value = partes.length > 1 ? partes[1].trim() : "";
  });
})();
