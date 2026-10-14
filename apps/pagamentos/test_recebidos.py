import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import cora_api
from apps.pagamentos.models import Pagamento, RecebimentoCora, Vencimento

pytestmark = pytest.mark.django_db


def _entrada(identificador, valor, nome="", documento=""):
    return {"id": identificador, "valor": Decimal(valor), "recebido_em": timezone.now(), "tipo": "PIX",
            "nome": nome, "documento": documento}


@pytest.fixture
def extrato(monkeypatch, settings):
    from django.core.cache import cache

    cache.clear()
    settings.CORA_PROVIDER = "cora"
    entradas = []
    monkeypatch.setattr(cora_api, "listar_extrato", lambda inicio, fim: list(entradas))
    return entradas


def test_pix_direto_vira_sugestao_pelo_cpf_e_a_baixa_liga_a_entrada(auth_client, cliente, extrato):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    extrato.append(_entrada("ent_1", "250.00", "OUTRO NOME NO BANCO", cliente.cpf))  # menos que a parcela: só a equipe resolve
    extrato.append(_entrada("ent_2", "50.00", "Desconhecido Total"))

    html = auth_client.get(reverse("pagamentos:recebidos")).content.decode()
    assert RecebimentoCora.objects.count() == 2
    assert cliente.nome in html and "mesmo CPF" in html and "Cliente não identificado" in html
    entrada = RecebimentoCora.objects.get(entrada_id="ent_1")

    pagina = auth_client.get(reverse("pagamentos:novo", args=[ct.pk]) + f"?recebido={entrada.pk}")
    assert pagina.context["form"].initial["valor_pago"] == "250,00" and pagina.context["form"].initial["forma"] == "pix"

    resposta = auth_client.post(reverse("pagamentos:novo", args=[ct.pk]), {
        "recebido": entrada.pk, "vencimento": venc.pk, "data_pagamento": timezone.localdate().isoformat(),
        "valor_pago": "250,00", "juros_pago": "0,00", "forma": "pix"})
    assert resposta.status_code == 302
    entrada.refresh_from_db()
    assert entrada.situacao == RecebimentoCora.Situacao.VINCULADO and entrada.pagamento == Pagamento.objects.get()

    ignorada = RecebimentoCora.objects.get(entrada_id="ent_2")
    auth_client.post(reverse("pagamentos:recebido_ignorar", args=[ignorada.pk]))
    ignorada.refresh_from_db()
    assert ignorada.situacao == RecebimentoCora.Situacao.IGNORADO


def test_pagamento_de_qr_do_sistema_nao_vira_pendencia(auth_client, cliente, extrato):
    from apps.pagamentos.models import CobrancaCora

    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)
    venc = Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("300.00"), data_vencimento=timezone.localdate())
    CobrancaCora.objects.create(vencimento=venc, valor=Decimal("300.00"), data_vencimento=venc.data_vencimento,
                                status=CobrancaCora.Status.PAGO, total_pago=Decimal("300.00"), pago_em=timezone.now())
    extrato.append(_entrada("ent_qr", "300.00", "Fulano", "00000000000"))
    auth_client.get(reverse("pagamentos:recebidos"))
    assert RecebimentoCora.objects.get().situacao == RecebimentoCora.Situacao.VINCULADO


def _contrato_com_parcela(cliente, dias_de_atraso=0, valor="300.00"):
    import datetime

    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela=valor, num_parcelas=3)
    venc = Vencimento.objects.create(
        contrato=ct, numero=1, valor_previsto=Decimal(valor),
        data_vencimento=timezone.localdate() - datetime.timedelta(days=dias_de_atraso))
    return ct, venc


def test_pix_com_cpf_e_valor_certos_da_baixa_sozinho(auth_client, cliente, extrato):
    ct, venc = _contrato_com_parcela(cliente, dias_de_atraso=2)  # parcela 300 + 2 dias de juros = 310
    extrato.append(_entrada("ent_ok", "310.00", "Fulano", cliente.cpf))
    auth_client.get(reverse("pagamentos:recebidos"))
    pagamento = Pagamento.objects.get()
    assert pagamento.vencimento == venc and pagamento.valor_pago == Decimal("300.00") and pagamento.juros_pago == Decimal("10.00")
    assert "extrato da Cora" in pagamento.observacao
    venc.refresh_from_db()
    assert venc.status == Vencimento.Status.PAGO
    assert RecebimentoCora.objects.get().situacao == RecebimentoCora.Situacao.VINCULADO


def test_quem_pagou_o_codigo_de_ontem_tambem_e_reconhecido(auth_client, cliente, extrato):
    _contrato_com_parcela(cliente, dias_de_atraso=3)  # hoje seria 315; ontem eram 310
    extrato.append(_entrada("ent_ontem", "310.00", "Fulano", cliente.cpf))
    auth_client.get(reverse("pagamentos:recebidos"))
    assert Pagamento.objects.get().juros_pago == Decimal("10.00")


def test_nao_da_baixa_sozinho_quando_e_duvidoso(auth_client, cliente, extrato):
    import datetime

    _contrato_com_parcela(cliente)  # parcela 300
    novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3)  # sem parcela: ignorado
    outro, v2 = _contrato_com_parcela(cliente)  # segunda parcela de 300: o mesmo valor casa com os dois contratos
    extrato.append(_entrada("ent_duvida", "300.00", "Fulano", cliente.cpf))
    antiga = _entrada("ent_antiga", "300.00", "Fulano", cliente.cpf)
    antiga["recebido_em"] = timezone.now() - datetime.timedelta(days=5)  # velha demais para baixa automática
    extrato.append(antiga)
    auth_client.get(reverse("pagamentos:recebidos"))
    assert not Pagamento.objects.exists()
    assert RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO).count() == 2


def test_pagamento_ja_registrado_a_mao_nao_e_duplicado(auth_client, cliente, extrato):
    ct, venc = _contrato_com_parcela(cliente)
    Pagamento.objects.create(contrato=ct, vencimento=venc, valor_pago=Decimal("300.00"),
                             data_pagamento=timezone.localdate(), forma="pix")
    ct2, venc2 = _contrato_com_parcela(cliente)
    extrato.append(_entrada("ent_manual", "300.00", "Fulano", cliente.cpf))
    auth_client.get(reverse("pagamentos:recebidos"))
    assert Pagamento.objects.count() == 1  # a entrada foi ligada ao pagamento existente, sem baixar a outra parcela
    assert RecebimentoCora.objects.get().situacao == RecebimentoCora.Situacao.VINCULADO
