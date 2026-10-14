"""Acordos: perdoar juros e marcar nova data de vencimento."""

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.clientes.situacao import situacoes_dos_clientes
from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos import acordos
from apps.pagamentos.agenda import parcelas_a_cobrar
from apps.pagamentos.models import Acordo, CobrancaCora, Pagamento, Vencimento
from apps.pagamentos.pix_cora import composicao_do_pix

pytestmark = pytest.mark.django_db


def HOJE():
    return timezone.localdate()


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def parcela(cliente):
    """Parcela 1 vencida há 10 dias (juros R$ 50) e parcela 2 daqui a 20 dias."""
    ct = novo_contrato(
        cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3,
        juros_diario=Decimal("5.00"),
    )
    v1 = Vencimento.objects.create(
        contrato=ct, numero=1, data_vencimento=HOJE() - datetime.timedelta(days=10), valor_previsto=Decimal("300.00"))
    Vencimento.objects.create(
        contrato=ct, numero=2, data_vencimento=HOJE() + datetime.timedelta(days=20), valor_previsto=Decimal("300.00"))
    return v1


def _recarrega(v):
    return Vencimento.objects.get(pk=v.pk)


# ── perdoar juros ──────────────────────────────────────────────────────────

def test_perdao_total_zera_o_juros_em_todos_os_calculos(parcela):
    assert acordos.juros_a_cobrar(parcela, HOJE()) == Decimal("50.00")
    acordo, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    assert acordo.juros_perdoados == Decimal("50.00") and acordo.ativo
    parcela = _recarrega(parcela)
    contrato = parcela.contrato

    assert parcelas_a_cobrar(contrato, HOJE())[0].juros == Decimal("0.00")
    assert composicao_do_pix(parcela, HOJE()) == (Decimal("300.00"), Decimal("0.00"))
    assert contrato.situacao_atraso().juros == Decimal("0.00")
    assert situacoes_dos_clientes([contrato.cliente_id])[contrato.cliente_id].devido == Decimal("300.00")


def test_perdao_parcial_e_o_juros_dos_dias_seguintes_continua(parcela):
    acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("20.00"))
    parcela = _recarrega(parcela)
    assert acordos.juros_a_cobrar(parcela, HOJE()) == Decimal("30.00")
    amanha = HOJE() + datetime.timedelta(days=1)
    assert acordos.juros_a_cobrar(parcela, amanha) == Decimal("35.00")  # mais um dia de atraso


def test_perdao_acima_do_juros_ou_sem_juros_e_recusado(parcela):
    with pytest.raises(acordos.AcordoInvalido, match="entre R\\$ 0,01 e R\\$ 50,00"):
        acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("50.01"))
    acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    with pytest.raises(acordos.AcordoInvalido, match="não tem juros"):
        acordos.aplicar_acordo(_recarrega(parcela), tipo=Acordo.Tipo.PERDAO_JUROS)


# ── nova data ──────────────────────────────────────────────────────────────

def test_nova_data_reinicia_o_atraso_e_guarda_a_data_original(parcela):
    original = parcela.data_vencimento
    nova = HOJE() + datetime.timedelta(days=5)
    acordo, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.NOVA_DATA, nova_data=nova)
    parcela = _recarrega(parcela)
    assert parcela.data_vencimento == nova and parcela.data_original == original
    assert acordo.data_anterior == original and acordo.nova_data == nova
    assert parcelas_a_cobrar(parcela.contrato, HOJE()) == []  # ainda não venceu: sai do "cobrar hoje"
    assert parcela.contrato.situacao_atraso().dias_atraso == 0
    # depois da nova data o juros volta a contar a partir dela
    daqui_a_8_dias = HOJE() + datetime.timedelta(days=8)
    assert acordos.juros_a_cobrar(parcela, daqui_a_8_dias) == Decimal("15.00")


def test_nova_data_zera_o_perdao_anterior(parcela):
    acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("10.00"))
    acordos.aplicar_acordo(_recarrega(parcela), tipo=Acordo.Tipo.NOVA_DATA, nova_data=HOJE() + datetime.timedelta(days=3))
    assert _recarrega(parcela).juros_abonado == Decimal("0.00")


@pytest.mark.parametrize("dias, trecho", [
    (-11, "depois da data de cobrança atual"),   # antes do vencimento atual
    (-5, "passado"),                       # depois do vencimento, mas já passou
    (21, "parcela seguinte"),              # além da parcela 2
])
def test_nova_data_invalida(parcela, dias, trecho):
    with pytest.raises(acordos.AcordoInvalido, match=trecho):
        acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.NOVA_DATA, nova_data=HOJE() + datetime.timedelta(days=dias))
    assert not Acordo.objects.exists()


def test_nova_data_exige_a_data(parcela):
    with pytest.raises(acordos.AcordoInvalido, match="Informe a nova data"):
        acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.NOVA_DATA)


# ── quando não dá para negociar ────────────────────────────────────────────

def test_parcela_paga_com_baixa_ou_contrato_quitado_nao_negocia(parcela):
    contrato = parcela.contrato
    Pagamento.objects.create(contrato=contrato, vencimento=parcela, valor_pago=Decimal("100.00"), data_pagamento=HOJE())
    with pytest.raises(acordos.AcordoInvalido, match="recebeu pagamento"):
        acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)

    Pagamento.objects.all().delete()
    contrato.status = Contrato.Status.QUITADO
    contrato.save()
    with pytest.raises(acordos.AcordoInvalido, match="quitado"):
        acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)


def test_tipo_desconhecido(parcela):
    with pytest.raises(acordos.AcordoInvalido, match="tipo de acordo"):
        acordos.aplicar_acordo(parcela, tipo="outro")


# ── desfazer ───────────────────────────────────────────────────────────────

def test_desfazer_perdao_devolve_o_juros(parcela):
    acordo, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("20.00"))
    acordos.desfazer_acordo(acordo)
    assert _recarrega(parcela).juros_abonado == Decimal("0.00")
    acordo.refresh_from_db()
    assert not acordo.ativo and not acordos.pode_desfazer(acordo)


def test_desfazer_nova_data_restaura_o_vencimento(parcela):
    original = parcela.data_vencimento
    acordo, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.NOVA_DATA, nova_data=HOJE() + datetime.timedelta(days=4))
    acordos.desfazer_acordo(acordo)
    parcela = _recarrega(parcela)
    assert parcela.data_vencimento == original and parcela.data_original is None


def test_so_o_acordo_mais_recente_da_parcela_pode_ser_desfeito(parcela):
    primeiro, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("10.00"))
    segundo, _ = acordos.aplicar_acordo(_recarrega(parcela), tipo=Acordo.Tipo.PERDAO_JUROS, juros_perdoar=Decimal("5.00"))
    assert not acordos.pode_desfazer(primeiro) and acordos.pode_desfazer(segundo)
    with pytest.raises(acordos.AcordoInvalido, match="mais recente"):
        acordos.desfazer_acordo(primeiro)
    acordos.desfazer_acordo(segundo)
    acordos.desfazer_acordo(primeiro)
    assert _recarrega(parcela).juros_abonado == Decimal("0.00")


def test_nao_desfaz_depois_do_pagamento(parcela):
    acordo, _ = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    Pagamento.objects.create(contrato=parcela.contrato, vencimento=parcela, valor_pago=Decimal("300.00"), data_pagamento=HOJE())
    assert not acordos.pode_desfazer(acordo)
    with pytest.raises(acordos.AcordoInvalido):
        acordos.desfazer_acordo(acordo)


# ── Pix ────────────────────────────────────────────────────────────────────

def test_pix_aberto_e_cancelado_e_liberado_para_gerar_outro(parcela, monkeypatch):
    pix = CobrancaCora.objects.create(
        vencimento=parcela, valor=Decimal("350.00"), juros=Decimal("50.00"), data_vencimento=parcela.data_vencimento,
        cora_id="fatura-1", status=CobrancaCora.Status.ABERTO)
    chamadas = []
    monkeypatch.setattr("apps.pagamentos.pix_cora.cancelar_cobranca", lambda p, **_: chamadas.append(("cancelar", p.pk)))
    monkeypatch.setattr("apps.pagamentos.pix_cora.retomar_cobranca", lambda p: chamadas.append(("retomar", p.pk)))
    _, avisos = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    assert chamadas == [("cancelar", pix.pk), ("retomar", pix.pk)]
    assert avisos and avisos[0][0] == "info"


def test_pix_sem_qr_vivo_nao_mexe_na_cora(parcela, monkeypatch):
    CobrancaCora.objects.create(
        vencimento=parcela, valor=Decimal("350.00"), data_vencimento=parcela.data_vencimento, status=CobrancaCora.Status.PENDENTE)
    monkeypatch.setattr("apps.pagamentos.pix_cora.cancelar_cobranca", lambda p: pytest.fail("não devia cancelar"))
    _, avisos = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    assert avisos == []


def test_falha_da_cora_no_cancelamento_vira_aviso_sem_perder_o_acordo(parcela, monkeypatch):
    from apps.pagamentos import cora_api

    CobrancaCora.objects.create(
        vencimento=parcela, valor=Decimal("350.00"), data_vencimento=parcela.data_vencimento,
        cora_id="fatura-1", status=CobrancaCora.Status.ABERTO)

    def _falha(_pix, **_):
        raise cora_api.CoraErro("fora do ar")

    monkeypatch.setattr("apps.pagamentos.pix_cora.cancelar_cobranca", _falha)
    acordo, avisos = acordos.aplicar_acordo(parcela, tipo=Acordo.Tipo.PERDAO_JUROS)
    assert acordo.pk and avisos[0][0] == "warning" and "painel Pix" in avisos[0][1]
    assert _recarrega(parcela).juros_abonado == Decimal("50.00")


# ── telas ──────────────────────────────────────────────────────────────────

def test_tela_do_acordo_mostra_a_situacao_da_parcela(auth_client, parcela):
    html = auth_client.get(reverse("pagamentos:acordo", args=[parcela.pk])).content.decode()
    assert "Negociar parcela 1" in html and "Perdoar juros" in html and "Nova data de cobrança" in html
    assert "10 dias" in html and "R$ 50,00" in html and "R$ 350,00" in html


def test_perdoar_juros_pela_tela(auth_client, parcela):
    resposta = auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {
        "tipo": "perdao_juros", "juros": "20,00", "nota": "Bom pagador"})
    assert resposta.status_code == 302 and resposta.url.endswith("#acordos")
    acordo = Acordo.objects.get()
    assert acordo.juros_perdoados == Decimal("20.00") and acordo.nota == "Bom pagador" and acordo.autor
    assert _recarrega(parcela).juros_abonado == Decimal("20.00")


def test_nova_data_pela_tela(auth_client, parcela):
    nova = (HOJE() + datetime.timedelta(days=6)).isoformat()
    resposta = auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "nova_data", "nova_data": nova})
    assert resposta.status_code == 302
    assert _recarrega(parcela).data_vencimento.isoformat() == nova


def test_erro_do_acordo_volta_para_a_tela_sem_gravar(auth_client, parcela):
    resposta = auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "perdao_juros", "juros": "999,00"})
    assert resposta.status_code == 200 and "entre R$ 0,01 e R$ 50,00" in resposta.content.decode()
    assert not Acordo.objects.exists()
    resposta = auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "nova_data", "nova_data": ""})
    assert resposta.status_code == 200 and not Acordo.objects.exists()


def test_detalhe_do_contrato_oferece_negociar_e_lista_os_acordos(auth_client, parcela):
    url = reverse("contratos:detalhe", args=[parcela.contrato.pk])
    html = auth_client.get(url).content.decode()
    assert reverse("pagamentos:acordo", args=[parcela.pk]) in html and "negociar" in html

    auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "perdao_juros", "juros": "50,00"})
    html = auth_client.get(url).content.decode()
    assert 'id="acordos"' in html and "de juros perdoados" in html and "Desfazer" in html
    assert "juros perdoados: R$ 50,00" in html


def test_desfazer_pela_tela(auth_client, parcela):
    auth_client.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "perdao_juros", "juros": "50,00"})
    acordo = Acordo.objects.get()
    resposta = auth_client.post(reverse("pagamentos:acordo_desfazer", args=[acordo.pk]))
    assert resposta.status_code == 302
    acordo.refresh_from_db()
    assert not acordo.ativo and _recarrega(parcela).juros_abonado == Decimal("0.00")


def test_telas_exigem_login(parcela):
    anonimo = Client()
    assert anonimo.get(reverse("pagamentos:acordo", args=[parcela.pk])).status_code == 302
    assert anonimo.post(reverse("pagamentos:acordo", args=[parcela.pk]), {"tipo": "perdao_juros", "juros": "5"}).status_code == 302
    assert not Acordo.objects.exists()


def test_baixa_sugere_o_total_das_parcelas_em_atraso(auth_client, cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3, juros_diario=Decimal("5.00"))
    for numero, dias in ((1, 10), (2, 2)):
        Vencimento.objects.create(contrato=ct, numero=numero, data_vencimento=HOJE() - datetime.timedelta(days=dias),
                                  valor_previsto=Decimal("300.00"))
    form = auth_client.get(reverse("pagamentos:novo", args=[ct.pk])).context["form"]
    assert form.initial["valor_pago"] == "600,00" and form.initial["juros_pago"] == "60,00"  # 50 + 10 de juros
    assert "1 + 2" in form.fields["valor_pago"].help_text


def test_baixa_deixa_escolher_quantas_parcelas_quita(auth_client, cliente):
    import json

    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="300.00", num_parcelas=3, juros_diario=Decimal("5.00"))
    for numero, dias in ((1, 10), (2, 2)):
        Vencimento.objects.create(contrato=ct, numero=numero, data_vencimento=HOJE() - datetime.timedelta(days=dias),
                                  valor_previsto=Decimal("300.00"))
    campo = auth_client.get(reverse("pagamentos:novo", args=[ct.pk])).context["form"].fields["quantidade"]
    assert [valor for valor, _ in campo.choices] == [1, 2]
    assert [p["juros"] for p in json.loads(campo.widget.attrs["data-parcelas"])] == ["50.00", "10.00"]
