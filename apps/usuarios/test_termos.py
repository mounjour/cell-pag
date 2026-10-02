import pytest
from django.urls import reverse

SENHA = "s3nha-forte-123"


@pytest.fixture
def pessoa(django_user_model):
    return django_user_model.objects.create_user(
        "ana", password=SENHA, first_name="Ana", email="ana@exemplo.com"
    )


@pytest.fixture
def logada(client, pessoa):
    client.force_login(pessoa)
    return client


# ---------- termos ----------


@pytest.mark.django_db
def test_termos_podem_ser_lidos_sem_login(client):
    html = client.get(reverse("usuarios:termos")).content.decode()
    assert "Termos de uso" in html and "Aviso de privacidade" in html
    assert "Aceitar e continuar" not in html


@pytest.mark.django_db
def test_login_mostra_o_link_dos_termos(client):
    assert reverse("usuarios:termos") in client.get(reverse("usuarios:login")).content.decode()


@pytest.mark.django_db
def test_quem_nao_aceitou_e_levado_para_os_termos(logada, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    resposta = logada.get(reverse("relatorios:inicio"))
    assert resposta.status_code == 302
    assert resposta["Location"].startswith(reverse("usuarios:termos"))
    assert "next=" in resposta["Location"]


@pytest.mark.django_db
def test_tela_de_termos_oferece_o_aceite_a_quem_nao_aceitou(logada, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    html = logada.get(reverse("usuarios:termos")).content.decode()
    assert "Aceitar e continuar" in html


@pytest.mark.django_db
def test_aceitar_grava_versao_e_data_e_libera_o_sistema(logada, pessoa, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    resposta = logada.post(
        reverse("usuarios:termos_aceitar"), {"aceito": "1", "next": reverse("clientes:lista")}
    )
    pessoa.refresh_from_db()
    assert resposta["Location"] == reverse("clientes:lista")
    assert pessoa.termos_aceitos_versao == settings.TERMOS_VERSAO
    assert pessoa.termos_aceitos_em is not None
    assert logada.get(reverse("relatorios:inicio")).status_code == 200


@pytest.mark.django_db
def test_aceite_sem_marcar_a_caixa_nao_vale(logada, pessoa, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    logada.post(reverse("usuarios:termos_aceitar"), {})
    pessoa.refresh_from_db()
    assert pessoa.termos_aceitos_versao == ""


@pytest.mark.django_db
def test_aceite_ignora_destino_de_outro_site(logada, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    resposta = logada.post(
        reverse("usuarios:termos_aceitar"), {"aceito": "1", "next": "https://mal.example.com/"}
    )
    assert resposta["Location"] == reverse("relatorios:inicio")


@pytest.mark.django_db
def test_nova_versao_dos_termos_pede_aceite_de_novo(logada, pessoa, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    pessoa.termos_aceitos_versao = "2020-01-01"
    pessoa.save()
    assert logada.get(reverse("relatorios:inicio")).status_code == 302


@pytest.mark.django_db
def test_sair_fica_livre_antes_do_aceite(logada, settings):
    settings.TERMOS_EXIGIR_ACEITE = True
    assert logada.post(reverse("usuarios:logout")).status_code == 302
    assert "/termos/" not in logada.post(reverse("usuarios:logout")).get("Location", "")
