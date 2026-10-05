import datetime
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from validate_docbr import CPF as CPFGen

from apps.clientes.models import Cliente
from apps.contratos.forms import moeda_para_decimal
from apps.contratos.test_helpers import cadastrar_contrato
from apps.contratos.models import Contrato


def dados_form(cliente, **over):
    dados = {
        "cliente": cliente.pk,
        "apelido": "iPhone 11",
        "aparelho_modelo": "iPhone 11",
        "imei": "359999053372501",
        "valor_total": "2400,00",
        "estrutura": Contrato.Estrutura.DIARIA,
        "valor_parcela": "",
        "num_parcelas": "",
        "data_inicio": "2026-08-01",
        "dia_referencia": "",
        "proximo_vencimento": "",
        "status": Contrato.Status.EM_DIA,
        "data_prevista_quitacao": "",
        "observacoes": "",
    }
    dados.update(over)
    return dados


@pytest.fixture
def cliente(db):
    c = Cliente(nome="Cliente Teste", cpf=CPFGen().generate(), telefone_whatsapp="+5583999990000")
    c.full_clean()
    c.save()
    return c


def novo_contrato(cliente, **kwargs):
    dados = dict(
        cliente=cliente,
        apelido="iPhone 11",
        aparelho_modelo="iPhone 11 64GB",
        valor_total="2400.00",
        estrutura=Contrato.Estrutura.DIARIA,
        data_inicio=datetime.date(2026, 8, 1),
    )
    dados.update(kwargs)
    return Contrato.objects.create(**dados)


# ---------- Modelo ----------

@pytest.mark.django_db
def test_contrato_minimo(cliente):
    ct = novo_contrato(cliente)
    assert ct.status == Contrato.Status.EM_DIA
    assert ct.valor_parcela is None  # cálculo é da Fase 2
    assert ct.proximo_vencimento is None
    assert not ct.quitado
    assert str(ct) == "Cliente Teste — iPhone 11"
    assert ct.numero_interno == f"CT-{ct.pk:04d}"


# ---------- Modelo: ligação com o cálculo de atraso (Fase 4) ----------

@pytest.mark.django_db
def test_situacao_atraso_sem_proximo_vencimento_e_none(cliente):
    ct = novo_contrato(cliente)
    assert ct.situacao_atraso() is None
    # status_efetivo cai no status salvo quando não há data de referência
    assert ct.status_efetivo == ct.status


@pytest.mark.django_db
def test_situacao_atraso_em_dia(cliente):
    hoje = datetime.date(2026, 9, 10)
    ct = novo_contrato(cliente, proximo_vencimento=hoje, estrutura=Contrato.Estrutura.MENSAL)
    s = ct.situacao_atraso(hoje=hoje)
    assert s.dias_atraso == 0
    assert s.status == Contrato.Status.EM_DIA
    assert s.juros == Decimal("0.00")
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_situacao_atraso_atrasado_com_juros(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 10),
        estrutura=Contrato.Estrutura.MENSAL,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 9, 12))
    assert s.dias_atraso == 2
    assert s.juros == Decimal("10.00")
    assert s.status == Contrato.Status.ATRASADO
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_situacao_atraso_inadimplente_dispara_alerta(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 1),
        estrutura=Contrato.Estrutura.DIARIA,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 9, 11))
    assert s.dias_atraso == 10
    assert s.status == Contrato.Status.INADIMPLENTE
    assert s.alertar_bloqueio is True


@pytest.mark.django_db
def test_situacao_atraso_semanal_usa_a_janela(cliente):
    # Vencimento numa quarta (2026-01-07); a semana fecha no domingo 2026-01-11.
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 1, 7),
        estrutura=Contrato.Estrutura.SEMANAL,
    )
    assert ct.situacao_atraso(hoje=datetime.date(2026, 1, 11)).dias_atraso == 0
    assert ct.situacao_atraso(hoje=datetime.date(2026, 1, 12)).dias_atraso == 1


@pytest.mark.django_db
def test_situacao_atraso_quitado_nao_cobra(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 1, 1),
        status=Contrato.Status.QUITADO,
    )
    s = ct.situacao_atraso(hoje=datetime.date(2026, 6, 1))
    assert s.status == Contrato.Status.QUITADO
    assert s.juros == Decimal("0.00")
    assert s.alertar_bloqueio is False


@pytest.mark.django_db
def test_sincronizar_status_grava_o_calculado(cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2026, 9, 1),
        estrutura=Contrato.Estrutura.MENSAL,
    )
    mudou = ct.sincronizar_status(hoje=datetime.date(2026, 9, 3))
    assert mudou is True
    ct.refresh_from_db()
    assert ct.status == Contrato.Status.ATRASADO
    # segunda chamada no mesmo dia não muda nada
    assert ct.sincronizar_status(hoje=datetime.date(2026, 9, 3)) is False


@pytest.mark.django_db
def test_sincronizar_status_sem_data_nao_mexe(cliente):
    ct = novo_contrato(cliente, status=Contrato.Status.ATRASADO)
    assert ct.sincronizar_status() is False
    ct.refresh_from_db()
    assert ct.status == Contrato.Status.ATRASADO


@pytest.mark.django_db
def test_detalhe_mostra_situacao_hoje(auth_client, cliente):
    ct = novo_contrato(
        cliente,
        proximo_vencimento=datetime.date(2020, 1, 1),  # bem no passado
        estrutura=Contrato.Estrutura.MENSAL,
    )
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    corpo = resp.content.decode()
    assert "Situação hoje" in corpo
    assert "de atraso" in corpo


# ---------- Telas ----------

@pytest.mark.django_db
def test_lista_exige_login(client):
    resp = client.get(reverse("contratos:lista"))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_lista_filtra_por_status(auth_client, cliente):
    novo_contrato(cliente, apelido="A", status=Contrato.Status.EM_DIA)
    novo_contrato(cliente, apelido="B", status=Contrato.Status.ATRASADO)
    resp = auth_client.get(reverse("contratos:lista"), {"status": "atrasado"})
    apelidos = {c.apelido for c in resp.context["contratos"]}
    assert apelidos == {"B"}


@pytest.mark.django_db
def test_lista_filtra_por_estrutura(auth_client, cliente):
    novo_contrato(cliente, apelido="A", estrutura=Contrato.Estrutura.MENSAL)
    novo_contrato(cliente, apelido="B", estrutura=Contrato.Estrutura.SEMANAL)
    resp = auth_client.get(reverse("contratos:lista"), {"estrutura": "mensal"})
    apelidos = {c.apelido for c in resp.context["contratos"]}
    assert apelidos == {"A"}


@pytest.mark.django_db
def test_lista_combina_filtro_de_estrutura_e_status(auth_client, cliente):
    novo_contrato(
        cliente, apelido="A", estrutura=Contrato.Estrutura.MENSAL, status=Contrato.Status.ATRASADO
    )
    novo_contrato(
        cliente, apelido="B", estrutura=Contrato.Estrutura.MENSAL, status=Contrato.Status.EM_DIA
    )
    novo_contrato(
        cliente, apelido="C", estrutura=Contrato.Estrutura.SEMANAL, status=Contrato.Status.ATRASADO
    )
    resp = auth_client.get(reverse("contratos:lista"), {"estrutura": "mensal", "status": "atrasado"})
    apelidos = {c.apelido for c in resp.context["contratos"]}
    assert apelidos == {"A"}


@pytest.mark.django_db
def test_lista_usa_status_calculado_no_badge_e_no_filtro(auth_client, cliente):
    # `status` salvo diz "em dia", mas o vencimento está bem no passado:
    # a lista deve mostrar/filtrar pelo status calculado (inadimplente).
    novo_contrato(
        cliente,
        apelido="Atrasadão",
        status=Contrato.Status.EM_DIA,
        estrutura=Contrato.Estrutura.MENSAL,
        proximo_vencimento=datetime.date(2020, 1, 1),
    )
    corpo = auth_client.get(reverse("contratos:lista")).content.decode()
    assert "INADIMPLENTE" in corpo.upper()

    achados = auth_client.get(reverse("contratos:lista"), {"status": "inadimplente"})
    assert [c.apelido for c in achados.context["contratos"]] == ["Atrasadão"]

    vazio = auth_client.get(reverse("contratos:lista"), {"status": "em_dia"})
    assert list(vazio.context["contratos"]) == []


@pytest.mark.django_db
def test_detalhe_renderiza(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    assert resp.status_code == 200
    assert resp.context["contrato"] == ct
    assert "form_documento" in resp.context


@pytest.mark.django_db
def test_novo_contrato_pre_preenche_cliente(auth_client, cliente):
    resp = auth_client.get(reverse("contratos:novo") + f"?cliente={cliente.pk}")
    assert resp.status_code == 200
    assert resp.context["form"].initial.get("cliente") == cliente


@pytest.mark.django_db
def test_editar_contrato(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.post(
        reverse("contratos:editar", args=[ct.pk]),
        dados_form(cliente, apelido="iPhone 11 Pro", estrutura=Contrato.Estrutura.SEMANAL),
    )
    assert resp.status_code == 302
    ct.refresh_from_db()
    assert ct.apelido == "iPhone 11 Pro"
    assert ct.estrutura == Contrato.Estrutura.SEMANAL


# ---------- Aparelho do estoque (apps.aparelhos) ----------

@pytest.mark.django_db
def test_escolher_aparelho_do_estoque_vincula_e_marca_como_vendido(auth_client, cliente):
    from apps.aparelhos.models import Aparelho

    ap = Aparelho.objects.create(modelo="iPhone 11 64GB", imei="123456789012345")
    resp = cadastrar_contrato(auth_client, dados_form(cliente, aparelho=ap.pk),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.aparelho_id == ap.pk
    ap.refresh_from_db()
    assert ap.vendido is True


@pytest.mark.django_db
def test_aparelho_ja_vendido_nao_aparece_pra_escolher_de_novo(auth_client, cliente):
    from apps.aparelhos.models import Aparelho

    ap = Aparelho.objects.create(modelo="iPhone 11")
    novo_contrato(cliente, aparelho=ap)
    outro_cliente = Cliente.objects.create(
        nome="Outro Cliente", cpf=CPFGen().generate(), telefone_whatsapp="+5583999992222"
    )
    resp = auth_client.get(reverse("contratos:novo"))
    queryset = resp.context["form"].fields["aparelho"].queryset
    assert ap not in queryset


@pytest.mark.django_db
def test_sem_escolher_aparelho_continua_funcionando_como_antes(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente), follow=True)
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.aparelho_id is None
    assert ct.aparelho_modelo == "iPhone 11"


# ---------- Gerar parcelas pela web (sem terminal) ----------

@pytest.mark.django_db
def test_cadastro_com_valor_parcela_ja_gera_vencimentos(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            estrutura=Contrato.Estrutura.MENSAL,
            valor_parcela="200,00",
            num_parcelas="12",
            data_inicio="2026-08-01",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.vencimentos.count() > 0
    assert ct.data_prevista_quitacao is not None
    assert "gerada(s) automaticamente" in resp.content.decode()


@pytest.mark.django_db
def test_cadastro_sem_num_parcelas_calcula_sozinho(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            valor_total="2400,00",
            estrutura=Contrato.Estrutura.MENSAL,
            valor_parcela="200,00",
            num_parcelas="",  # deixado em branco de propósito
            data_inicio="2026-08-01",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.num_parcelas == 12  # 2400 / 200
    assert ct.data_prevista_quitacao is not None  # já usa o num_parcelas calculado


@pytest.mark.django_db
def test_cadastro_com_num_parcelas_informado_nao_e_sobrescrito(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            valor_total="2400,00",
            estrutura=Contrato.Estrutura.MENSAL,
            valor_parcela="200,00",
            num_parcelas="20",  # divergente do cálculo (12) — decisão do vendedor
            data_inicio="2026-08-01",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.num_parcelas == 20


@pytest.mark.django_db
def test_cadastro_sem_valor_parcela_nao_gera_nada(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente, valor_parcela="", num_parcelas=""),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.vencimentos.count() == 0


@pytest.mark.django_db
def test_gerar_vencimentos_via_web_cria_parcelas(auth_client, cliente):
    ct = novo_contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("200.00"),
        num_parcelas=12,
        data_inicio=datetime.date(2026, 8, 1),
    )
    resp = auth_client.post(reverse("contratos:gerar_vencimentos", args=[ct.pk]), follow=True)
    assert resp.status_code == 200
    assert ct.vencimentos.count() > 0
    assert "parcela(s) gerada(s)" in resp.content.decode()
    ct.refresh_from_db()
    assert ct.data_prevista_quitacao is not None


@pytest.mark.django_db
def test_gerar_vencimentos_via_web_e_idempotente(auth_client, cliente):
    ct = novo_contrato(
        cliente,
        estrutura=Contrato.Estrutura.MENSAL,
        valor_parcela=Decimal("200.00"),
        num_parcelas=12,
    )
    url = reverse("contratos:gerar_vencimentos", args=[ct.pk])
    auth_client.post(url)
    total = ct.vencimentos.count()
    resp = auth_client.post(url, follow=True)
    assert ct.vencimentos.count() == total  # segunda vez não duplica
    assert "Nenhuma parcela nova" in resp.content.decode()


@pytest.mark.django_db
def test_gerar_vencimentos_via_web_sem_valor_parcela_avisa(auth_client, cliente):
    ct = novo_contrato(cliente)  # valor_parcela = None
    resp = auth_client.post(
        reverse("contratos:gerar_vencimentos", args=[ct.pk]), follow=True
    )
    assert ct.vencimentos.count() == 0
    assert "Informe o valor da parcela" in resp.content.decode()


@pytest.mark.django_db
def test_gerar_vencimentos_via_web_contrato_quitado_nao_gera(auth_client, cliente):
    ct = novo_contrato(
        cliente,
        status=Contrato.Status.QUITADO,
        valor_parcela=Decimal("200.00"),
        num_parcelas=12,
    )
    resp = auth_client.post(
        reverse("contratos:gerar_vencimentos", args=[ct.pk]), follow=True
    )
    assert ct.vencimentos.count() == 0
    assert "Contrato quitado" in resp.content.decode()


@pytest.mark.django_db
def test_gerar_vencimentos_via_web_exige_login(client, cliente):
    ct = novo_contrato(cliente)
    resp = client.post(reverse("contratos:gerar_vencimentos", args=[ct.pk]))
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_detalhe_mostra_botao_gerar_quando_nao_ha_parcelas(auth_client, cliente):
    ct = novo_contrato(cliente, valor_parcela=Decimal("200.00"), num_parcelas=12)
    corpo = auth_client.get(reverse("contratos:detalhe", args=[ct.pk])).content.decode()
    assert reverse("contratos:gerar_vencimentos", args=[ct.pk]) in corpo
    assert "Gerar parcelas" in corpo


@pytest.mark.django_db
def test_detalhe_sem_valor_parcela_manda_editar_o_contrato(auth_client, cliente):
    ct = novo_contrato(cliente)  # valor_parcela = None
    corpo = auth_client.get(reverse("contratos:detalhe", args=[ct.pk])).content.decode()
    assert "manage.py gerar_vencimentos" not in corpo
    assert reverse("contratos:editar", args=[ct.pk]) in corpo


# ---------- Formulário: entrada de dados no celular ----------

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("2400", Decimal("2400")),
        ("", None),
    ],
)
def test_moeda_para_decimal(entrada, esperado):
    assert moeda_para_decimal(entrada) == esperado


@pytest.mark.django_db
def test_form_aceita_valor_com_virgula(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente, valor_total="1.899,90", valor_parcela="63,33"),
    )
    assert resp.status_code == 302
    ct = Contrato.objects.get()
    assert ct.valor_total == Decimal("1899.90")
    assert ct.valor_parcela == Decimal("63.33")


@pytest.mark.django_db
def test_form_valor_invalido_mostra_erro(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente, valor_total="abc"))
    assert resp.status_code == 200
    assert "valor_total" in resp.context["form"].errors
    assert not Contrato.objects.exists()


@pytest.mark.django_db
def test_form_normaliza_imei(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente, imei="35 999905 337250 1"),
    )
    assert resp.status_code == 302
    assert Contrato.objects.get().imei == "359999053372501"


@pytest.mark.django_db
def test_anexar_documento_registra_enviado_por(auth_client, operador, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = novo_contrato(cliente, apelido="A", estrutura=Contrato.Estrutura.SEMANAL)
    arquivo = SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf")
    resp = auth_client.post(
        reverse("contratos:documento_novo", args=[ct.pk]),
        {"tipo": "contrato_assinado", "descricao": "assinado", "arquivo": arquivo},
    )
    assert resp.status_code == 302
    doc = ct.documentos.get()
    assert doc.enviado_por == operador
    assert doc.tipo == "contrato_assinado"


@pytest.mark.django_db
def test_anexo_rejeita_extensao_proibida(auth_client, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = novo_contrato(cliente, apelido="B", estrutura=Contrato.Estrutura.SEMANAL)
    exe = SimpleUploadedFile("virus.exe", b"MZ conteudo", content_type="application/octet-stream")
    resp = auth_client.post(
        reverse("contratos:documento_novo", args=[ct.pk]),
        {"tipo": "outro", "arquivo": exe},
    )
    assert resp.status_code == 302          # form_invalid volta para o detalhe
    assert ct.documentos.count() == 0       # nada foi salvo


@pytest.mark.django_db
def test_download_documento_exige_login(client, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = novo_contrato(cliente, apelido="C", estrutura=Contrato.Estrutura.SEMANAL)
    doc = ct.documentos.create(
        tipo="outro",
        arquivo=SimpleUploadedFile("doc.pdf", b"%PDF-1.4 x", content_type="application/pdf"),
    )
    resp = client.get(reverse("contratos:documento_baixar", args=[doc.pk]))
    assert resp.status_code == 302 and "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_download_documento_autenticado_como_anexo(auth_client, cliente, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    ct = novo_contrato(cliente, apelido="D", estrutura=Contrato.Estrutura.SEMANAL)
    doc = ct.documentos.create(
        tipo="outro",
        arquivo=SimpleUploadedFile("doc.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf"),
    )
    resp = auth_client.get(reverse("contratos:documento_baixar", args=[doc.pk]))
    assert resp.status_code == 200
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in resp["Content-Disposition"]
    assert b"".join(resp.streaming_content) == b"%PDF-1.4 conteudo"


# ---------- Comando seed_demo ----------

@pytest.mark.django_db
def test_seed_demo_cria_massa_variada():
    call_command("seed_demo")
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10

    # Um cliente fica sem contrato de propósito.
    assert Cliente.objects.filter(contratos__isnull=True).count() == 1

    # As 5 estruturas aparecem.
    estruturas = set(Contrato.objects.values_list("estrutura", flat=True))
    assert estruturas == {e.value for e in Contrato.Estrutura}

    # Situações-chave: um quitado, um sem próximo vencimento, e pelo menos um
    # inadimplente com alerta de bloqueio pelo cálculo de hoje.
    assert Contrato.objects.filter(status=Contrato.Status.QUITADO).count() == 1
    assert Contrato.objects.filter(proximo_vencimento__isnull=True).count() == 1
    situacoes = [ct.situacao_atraso() for ct in Contrato.objects.all()]
    assert any(s and s.alertar_bloqueio for s in situacoes)


@pytest.mark.django_db
def test_seed_demo_idempotente_e_reset():
    call_command("seed_demo")
    call_command("seed_demo")  # rodar de novo não duplica
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10

    call_command("seed_demo", "--reset")
    assert Cliente.objects.count() == 10
    assert Contrato.objects.count() == 10


@pytest.mark.django_db
def test_tela_do_contrato_longo_mostra_as_parcelas_atuais_e_nao_as_24_primeiras(auth_client):
    from apps.pagamentos.models import Vencimento
    from apps.contratos.views import LIMITE_PARCELAS_NO_CONTRATO, _parcelas_relevantes

    cliente = Cliente.objects.create(
        nome="Cliente Longo", cpf=CPFGen().generate(), telefone_whatsapp="+5583999996666"
    )
    ct = Contrato.objects.create(
        cliente=cliente, apelido="Longo", aparelho_modelo="X",
        valor_total=Decimal("600.00"), estrutura=Contrato.Estrutura.DIARIA,
        valor_parcela=Decimal("10.00"), num_parcelas=60, data_inicio=datetime.date(2026, 1, 1),
    )
    for n in range(1, 61):
        Vencimento.objects.create(
            contrato=ct, numero=n, valor_previsto=Decimal("10.00"),
            data_vencimento=datetime.date(2026, 1, 1) + datetime.timedelta(days=n),
            status=Vencimento.Status.PAGO if n <= 40 else Vencimento.Status.ABERTO,
            valor_pago=Decimal("10.00") if n <= 40 else Decimal("0.00"),
        )
    numeros = [v.numero for v in _parcelas_relevantes(list(ct.vencimentos.all()))]
    assert len(numeros) == LIMITE_PARCELAS_NO_CONTRATO
    assert 41 in numeros and 38 in numeros  # a 1ª em aberto e um pouco de contexto antes
    assert 1 not in numeros
    todas = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]), {"todas": "1"})
    assert len(todas.context["vencimentos_exibidos"]) == 60


# ---------- Contrato já em andamento: marcar parcelas já pagas ----------

@pytest.mark.django_db
def test_parcelas_ja_pagas_marca_as_primeiras_parcelas_como_pagas(auth_client, cliente):
    from apps.pagamentos.models import Pagamento, Vencimento

    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            estrutura=Contrato.Estrutura.DIARIA,
            valor_parcela="40,00",
            num_parcelas="10",
            data_inicio="2026-09-20",
            parcelas_ja_pagas="3",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.vencimentos.count() == 10

    pagas = ct.vencimentos.filter(numero__lte=3).order_by("numero")
    assert all(v.status == Vencimento.Status.PAGO for v in pagas)
    for v in pagas:
        pagamento = Pagamento.objects.get(vencimento=v)
        assert pagamento.valor_pago == v.valor_previsto
        assert pagamento.data_pagamento == v.data_vencimento
        assert pagamento.forma == Pagamento.Forma.OUTRO

    seguinte = ct.vencimentos.get(numero=4)
    assert seguinte.status == Vencimento.Status.ABERTO
    assert "3 parcela(s) anterior(es)" in resp.content.decode()


@pytest.mark.django_db
def test_parcelas_ja_pagas_sem_parcelas_geradas_avisa(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            estrutura=Contrato.Estrutura.DIARIA,
            valor_parcela="",  # sem valor de parcela: nada é gerado
            num_parcelas="",
            data_inicio="2026-09-20",
            parcelas_ja_pagas="2",
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    assert ct.vencimentos.count() == 0
    assert "não foram marcadas" in resp.content.decode()


@pytest.mark.django_db
def test_parcelas_ja_pagas_nao_pode_passar_do_num_parcelas(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            estrutura=Contrato.Estrutura.DIARIA,
            valor_parcela="40,00",
            num_parcelas="5",
            data_inicio="2026-09-20",
            parcelas_ja_pagas="10",
        ),
    )
    assert resp.status_code == 200  # form volta com erro, não redireciona
    assert not Contrato.objects.filter(cliente=cliente).exists()
    assert "Não pode ser maior que o nº de parcelas" in resp.content.decode()


@pytest.mark.django_db
def test_parcelas_ja_pagas_nao_aparece_na_edicao(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.get(reverse("contratos:editar", args=[ct.pk]))
    assert "parcelas_ja_pagas" not in resp.context["form"].fields


# ---------- Entrada (valor à vista no fechamento, à parte das parcelas) ----------

@pytest.mark.django_db
def test_entrada_vira_pagamento_sem_parcela_vinculada(auth_client, cliente):
    from apps.pagamentos.models import Pagamento

    resp = cadastrar_contrato(auth_client, dados_form(
            cliente,
            valor_total="1000,00",
            estrutura=Contrato.Estrutura.MENSAL,
            valor_parcela="100,00",
            num_parcelas="10",
            data_inicio="2026-09-01",
            entrada="200,00",
            entrada_forma=Pagamento.Forma.DINHEIRO,
        ),
        follow=True,
    )
    assert resp.status_code == 200
    ct = Contrato.objects.get(cliente=cliente)
    pagamento = Pagamento.objects.get(contrato=ct, vencimento__isnull=True)
    assert pagamento.valor_pago == Decimal("200.00")
    assert pagamento.forma == Pagamento.Forma.DINHEIRO
    assert pagamento.data_pagamento == datetime.date(2026, 9, 1)
    assert "Entrada de R$ 200,00 registrada" in resp.content.decode()
    # o valor total financiado não muda — a entrada é à parte
    assert ct.valor_total == Decimal("1000.00")
    # não conta como parcela: continuam todas em aberto
    assert not ct.vencimentos.filter(status="pago").exists()


@pytest.mark.django_db
def test_sem_entrada_nao_cria_pagamento_nenhum(auth_client, cliente):
    from apps.pagamentos.models import Pagamento

    cadastrar_contrato(auth_client, dados_form(cliente, entrada=""))
    ct = Contrato.objects.get(cliente=cliente)
    assert not Pagamento.objects.filter(contrato=ct).exists()


@pytest.mark.django_db
def test_entrada_aparece_na_tela_do_contrato(auth_client, cliente):
    from apps.pagamentos.models import Pagamento

    cadastrar_contrato(auth_client, dados_form(
            cliente,
            valor_total="1000,00",
            estrutura=Contrato.Estrutura.MENSAL,
            valor_parcela="100,00",
            num_parcelas="10",
            data_inicio="2026-09-01",
            entrada="150,50",
            entrada_forma=Pagamento.Forma.PIX,
        ),
    )
    ct = Contrato.objects.get(cliente=cliente)
    resp = auth_client.get(reverse("contratos:detalhe", args=[ct.pk]))
    corpo = resp.content.decode()
    assert "Entrada" in corpo
    assert "150,50" in corpo
    assert "Pix" in corpo


@pytest.mark.django_db
def test_entrada_zero_ou_negativa_e_invalida(auth_client, cliente):
    from apps.pagamentos.models import Pagamento

    resp = cadastrar_contrato(auth_client, dados_form(cliente, entrada="0,00", entrada_forma=Pagamento.Forma.DINHEIRO),
    )
    assert resp.status_code == 200
    assert not Contrato.objects.filter(cliente=cliente).exists()
    assert "maior que zero" in resp.content.decode()


@pytest.mark.django_db
def test_entrada_nao_aparece_na_edicao(auth_client, cliente):
    ct = novo_contrato(cliente)
    resp = auth_client.get(reverse("contratos:editar", args=[ct.pk]))
    assert "entrada" not in resp.context["form"].fields
    assert "entrada_forma" not in resp.context["form"].fields


@pytest.mark.django_db
def test_contrato_exige_imei(auth_client, cliente):
    resp = cadastrar_contrato(auth_client, dados_form(cliente, imei=""), follow=False)
    assert resp.status_code == 200
    assert not Contrato.objects.exists()
    assert "imei" in resp.context["form"].errors
