"""Busca global e esqueleto de navegação (menu lateral, barra inferior, contador)."""

import datetime
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato

_SENHA = "s3nha-forte-1234"


@pytest.fixture(autouse=True)
def _cache_limpo():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def logado(client, django_user_model):
    u = django_user_model.objects.create_user(
        "busca", password=_SENHA, email="busca@exemplo.com", first_name="Bia", is_staff=True
    )
    client.post(reverse("usuarios:login"), {"username": "busca", "password": _SENHA})
    return u


@pytest.fixture
def dados(db):
    ana = Cliente.objects.create(
        nome="Ana Souza", cpf="11144477735", telefone_whatsapp="+5583988887777"
    )
    Cliente.objects.create(
        nome="Bruno Lima", cpf="52998224725", telefone_whatsapp="+5583977776666", ativo=False
    )
    ct = Contrato.objects.create(
        cliente=ana, apelido="Moto G54", aparelho_modelo="Motorola G54 128GB", imei="356938035643809",
        estrutura="mensal", valor_total=Decimal("1800.00"), data_inicio=datetime.date(2026, 1, 5),
    )
    return ana, ct


def _buscar(client, q):
    return client.get(reverse("buscar"), {"q": q}).content.decode()


# ---------- Busca global ----------

@pytest.mark.django_db
def test_busca_exige_login(client):
    resp = client.get(reverse("buscar"), {"q": "ana"})
    assert resp.status_code == 302 and "/entrar/" in resp.url


@pytest.mark.django_db
def test_busca_por_nome_do_cliente(client, logado, dados):
    html = _buscar(client, "ana")
    assert "Ana Souza" in html and "Bruno Lima" not in html


@pytest.mark.django_db
def test_busca_por_cpf_com_ou_sem_pontuacao(client, logado, dados):
    assert "Ana Souza" in _buscar(client, "111.444.777-35")
    assert "Ana Souza" in _buscar(client, "11144477735")


@pytest.mark.django_db
def test_busca_acha_contrato_por_apelido_imei_e_numero(client, logado, dados):
    ana, ct = dados
    for termo in ("Moto G54", "356938", ct.numero_interno, ct.numero_interno.lower()):
        html = _buscar(client, termo)
        assert reverse("contratos:detalhe", args=[ct.pk]) in html, termo


@pytest.mark.django_db
def test_busca_mostra_cliente_arquivado_com_selo(client, logado, dados):
    html = _buscar(client, "bruno")
    assert "Bruno Lima" in html and "arquivado" in html


@pytest.mark.django_db
def test_busca_curta_vazia_e_sem_resultado(client, logado, dados):
    assert "pelo menos 2 caracteres" in _buscar(client, "a")
    assert "Nada encontrado" in _buscar(client, "zzzzzz")
    assert "Digite o nome ou CPF" in client.get(reverse("buscar")).content.decode()


# ---------- Menu ----------

@pytest.mark.django_db
def test_menu_agrupado_com_historico_e_sem_admin_na_lista(client, logado, dados):
    html = client.get(reverse("clientes:lista")).content.decode()
    for rotulo in ("Dia a dia", "Cadastros", "Histórico", "Cobrar hoje", "Pix"):
        assert rotulo in html
    lateral = html.split('<nav class="nav"', 1)[1].split("</nav>", 1)[0]
    assert "/admin/" not in lateral          # Admin saiu da lista do menu...
    assert "/admin/" in html                 # ...e foi para o menu do usuário (staff)


@pytest.mark.django_db
def test_relatorios_so_para_dono(client, logado, django_user_model):
    html = client.get(reverse("clientes:lista")).content.decode()
    assert "Análise" not in html and f'href="{reverse("relatorios:painel")}"' not in html
    logado.perfil = "dono"
    logado.save()
    html = client.get(reverse("clientes:lista")).content.decode()
    assert "Análise" in html and f'href="{reverse("relatorios:painel")}"' in html


@pytest.mark.django_db
def test_menu_mostra_nome_e_barra_inferior(client, logado):
    html = client.get(reverse("clientes:lista")).content.decode()
    assert 'class="tabbar"' in html and "Mais" in html
    assert '<span class="user-name">Bia</span>' in html
    assert 'name="q"' in html and reverse("buscar") in html


# ---------- Contador de "Cobrar hoje" ----------

@pytest.mark.django_db
def test_contador_aparece_quando_ha_cobranca_e_sumido_quando_nao(client, logado, dados):
    ana, ct = dados
    html = client.get(reverse("clientes:lista")).content.decode()
    assert 'class="selo"' not in html            # contrato novo, sem próximo vencimento

    ct.proximo_vencimento = datetime.date.today() - datetime.timedelta(days=3)
    ct.save()                                     # salvar o contrato invalida o cache
    html = client.get(reverse("clientes:lista")).content.decode()
    assert 'class="selo"' in html
    assert "1 para cobrar hoje" in html


@pytest.mark.django_db
def test_contador_e_guardado_em_cache(client, logado, dados, django_assert_num_queries):
    from apps.pagamentos.badge import contagem_cobrar_hoje

    contagem_cobrar_hoje()  # aquece
    with django_assert_num_queries(0):
        contagem_cobrar_hoje()


# ---------- Sugestões enquanto digita ----------

@pytest.mark.django_db
def test_sugestoes_exigem_login(client):
    resp = client.get(reverse("buscar_sugestoes"), {"q": "ana"})
    assert resp.status_code == 302 and "/entrar/" in resp.url


@pytest.mark.django_db
def test_sugestoes_devolvem_json_curto(client, logado, dados):
    ana, ct = dados
    resp = client.get(reverse("buscar_sugestoes"), {"q": "ana"})
    assert resp.status_code == 200
    dado = resp.json()
    assert dado["q"] == "ana"
    assert dado["clientes"][0]["titulo"] == "Ana Souza"
    assert dado["clientes"][0]["url"] == reverse("clientes:detalhe", args=[ana.pk])
    assert dado["contratos"][0]["titulo"] == f"{ct.numero_interno} · Moto G54"
    assert dado["contratos"][0]["detalhe"] == "Ana Souza"


@pytest.mark.django_db
def test_sugestoes_com_menos_de_2_letras_vem_vazio(client, logado, dados):
    dado = client.get(reverse("buscar_sugestoes"), {"q": "a"}).json()
    assert dado["clientes"] == [] and dado["contratos"] == []


@pytest.mark.django_db
def test_sugestoes_limitam_a_5_por_grupo(client, logado, db):
    for i in range(8):
        Cliente.objects.create(nome=f"Teste {i}", cpf=f"{i:011d}", telefone_whatsapp=f"+55839888800{i:02d}")
    dado = client.get(reverse("buscar_sugestoes"), {"q": "Teste"}).json()
    assert len(dado["clientes"]) == 5


@pytest.mark.django_db
def test_campo_do_topo_esta_ligado_as_sugestoes(client, logado):
    html = client.get(reverse("clientes:lista")).content.decode()
    assert reverse("buscar_sugestoes") in html and 'role="combobox"' in html and "js/busca.js" in html
