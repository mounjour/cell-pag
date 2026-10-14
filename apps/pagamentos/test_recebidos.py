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
    extrato.append(_entrada("ent_1", "300.00", "OUTRO NOME NO BANCO", cliente.cpf))
    extrato.append(_entrada("ent_2", "50.00", "Desconhecido Total"))

    html = auth_client.get(reverse("pagamentos:recebidos")).content.decode()
    assert RecebimentoCora.objects.count() == 2
    assert cliente.nome in html and "mesmo CPF" in html and "Cliente não identificado" in html
    entrada = RecebimentoCora.objects.get(entrada_id="ent_1")

    pagina = auth_client.get(reverse("pagamentos:novo", args=[ct.pk]) + f"?recebido={entrada.pk}")
    assert pagina.context["form"].initial["valor_pago"] == "300,00" and pagina.context["form"].initial["forma"] == "pix"

    resposta = auth_client.post(reverse("pagamentos:novo", args=[ct.pk]), {
        "recebido": entrada.pk, "vencimento": venc.pk, "data_pagamento": timezone.localdate().isoformat(),
        "valor_pago": "300,00", "juros_pago": "0,00", "forma": "pix"})
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
