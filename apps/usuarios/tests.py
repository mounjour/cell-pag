import pytest
from axes.utils import reset
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from django.views.generic import View

from apps.usuarios.mixins import DonoRequeridoMixin


class _TelaDono(DonoRequeridoMixin, View):
    def get(self, request, *args, **kwargs):
        from django.http import HttpResponse

        return HttpResponse("ok")


# ---------- Usuario.is_dono / is_financeiro ----------

@pytest.mark.django_db
def test_perfil_financeiro_nao_e_dono(django_user_model):
    u = django_user_model.objects.create_user("fin", password="x")
    assert u.perfil == django_user_model.Perfil.FINANCEIRO
    assert u.is_financeiro is True
    assert u.is_dono is False


@pytest.mark.django_db
def test_perfil_dono(django_user_model):
    u = django_user_model.objects.create_user(
        "dono", password="x", perfil=django_user_model.Perfil.DONO
    )
    assert u.is_dono is True
    assert u.is_financeiro is False


@pytest.mark.django_db
def test_superusuario_conta_como_dono(django_user_model):
    u = django_user_model.objects.create_superuser("root", password="x")
    assert u.is_dono is True


# ---------- DonoRequeridoMixin ----------

@pytest.mark.django_db
def test_mixin_anonimo_vai_para_login():
    req = RequestFactory().get("/relatorios/")
    req.user = AnonymousUser()
    resp = _TelaDono.as_view()(req)
    assert resp.status_code == 302
    assert "/entrar/" in resp["Location"]


@pytest.mark.django_db
def test_mixin_financeiro_recebe_403(django_user_model):
    req = RequestFactory().get("/relatorios/")
    req.user = django_user_model.objects.create_user("fin", password="x")
    with pytest.raises(PermissionDenied):
        _TelaDono.as_view()(req)


@pytest.mark.django_db
def test_mixin_dono_passa(django_user_model):
    req = RequestFactory().get("/relatorios/")
    req.user = django_user_model.objects.create_user(
        "dono", password="x", perfil=django_user_model.Perfil.DONO
    )
    resp = _TelaDono.as_view()(req)
    assert resp.status_code == 200


# ---------- Força-bruta no login (django-axes) ----------

_LOGIN_URL = reverse("usuarios:login")
_SENHA = "s3nha-forte-1234"
_SENHA_ADMIN = "Senha-forte-731"


@pytest.fixture(autouse=True)
def _limpa_axes():
    reset()
    yield
    reset()


@pytest.mark.django_db
def test_login_trava_no_limite(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 3
    django_user_model.objects.create_user("op", password=_SENHA)

    # As (limite - 1) primeiras falhas ainda re-renderizam o formulário.
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        resposta = client.post(_LOGIN_URL, {"username": "op", "password": "errada"})
        assert resposta.status_code == 200

    # A falha que atinge o limite já vem travada.
    travado = client.post(_LOGIN_URL, {"username": "op", "password": "errada"})
    assert travado.status_code == 429

    # Enquanto travado, nem a senha certa passa.
    com_senha_certa = client.post(_LOGIN_URL, {"username": "op", "password": _SENHA})
    assert com_senha_certa.status_code == 429


@pytest.mark.django_db
def test_tela_de_bloqueio_e_amigavel(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 2
    django_user_model.objects.create_user("op-bloq", password=_SENHA)

    for _ in range(settings.AXES_FAILURE_LIMIT):
        travado = client.post(_LOGIN_URL, {"username": "op-bloq", "password": "errada"})

    assert travado.status_code == 429
    assert travado["Content-Type"].startswith("text/html")
    corpo = travado.content.decode()
    assert "Muitas tentativas" in corpo
    assert "axes_reset_username" in corpo


@pytest.mark.django_db
def test_login_valido_dentro_do_limite(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 5
    django_user_model.objects.create_user("op2", password=_SENHA)

    client.post(_LOGIN_URL, {"username": "op2", "password": "errada"})
    entrou = client.post(_LOGIN_URL, {"username": "op2", "password": _SENHA})
    assert entrou.status_code == 302


# ---------- Login por usuário OU e-mail ----------

@pytest.mark.django_db
def test_login_por_email_funciona(client, django_user_model):
    django_user_model.objects.create_user("op4", password=_SENHA, email="op4@exemplo.com")
    resp = client.post(_LOGIN_URL, {"username": "op4@exemplo.com", "password": _SENHA})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_login_por_email_ignora_maiusculas(client, django_user_model):
    django_user_model.objects.create_user("op5", password=_SENHA, email="Op5@Exemplo.com")
    resp = client.post(_LOGIN_URL, {"username": "OP5@EXEMPLO.COM", "password": _SENHA})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_login_continua_funcionando_por_username(client, django_user_model):
    django_user_model.objects.create_user("op6", password=_SENHA, email="op6@exemplo.com")
    resp = client.post(_LOGIN_URL, {"username": "op6", "password": _SENHA})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_login_email_de_outro_usuario_nao_cola_com_senha_errada(client, django_user_model):
    django_user_model.objects.create_user("op7", password=_SENHA, email="op7@exemplo.com")
    resp = client.post(_LOGIN_URL, {"username": "op7@exemplo.com", "password": "errada-123"})
    assert resp.status_code == 200
    assert "Usuário ou senha inválidos" in resp.content.decode()


@pytest.mark.django_db
def test_login_email_inexistente_nao_quebra(client, django_user_model):
    resp = client.post(_LOGIN_URL, {"username": "ninguem@exemplo.com", "password": _SENHA})
    assert resp.status_code == 200


@pytest.mark.django_db
def test_rotulo_do_campo_convida_a_usar_email(client):
    corpo = client.get(_LOGIN_URL).content.decode()
    assert "Usuário ou e-mail" in corpo


# ---------- Content-Security-Policy ----------

@pytest.mark.django_db
def test_resposta_tem_csp_restritivo(client):
    csp = client.get(_LOGIN_URL).headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.django_db
def test_sucesso_zera_o_contador(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 3
    django_user_model.objects.create_user("op3", password=_SENHA)

    client.post(_LOGIN_URL, {"username": "op3", "password": "errada"})
    client.post(_LOGIN_URL, {"username": "op3", "password": "errada"})
    client.post(_LOGIN_URL, {"username": "op3", "password": _SENHA})  # AXES_RESET_ON_SUCCESS
    client.get(reverse("usuarios:logout"))

    # Contador zerado: mais duas falhas não travam.
    for _ in range(2):
        resposta = client.post(_LOGIN_URL, {"username": "op3", "password": "errada"})
        assert resposta.status_code == 200


# ---------- Manter conectado ----------

@pytest.mark.django_db
def test_login_sem_marcar_usa_sessao_padrao(client, django_user_model, settings):
    django_user_model.objects.create_user("mc1", password=_SENHA)
    resp = client.post(_LOGIN_URL, {"username": "mc1", "password": _SENHA})
    assert resp.status_code == 302
    assert client.session.get_expiry_age() == pytest.approx(settings.SESSION_COOKIE_AGE, abs=5)


@pytest.mark.django_db
def test_login_manter_conectado_estende_a_sessao(client, django_user_model, settings):
    django_user_model.objects.create_user("mc2", password=_SENHA)
    resp = client.post(
        _LOGIN_URL, {"username": "mc2", "password": _SENHA, "manter_conectado": "on"}
    )
    assert resp.status_code == 302
    esperado = settings.SESSION_MANTER_CONECTADO_DIAS * 24 * 60 * 60
    assert client.session.get_expiry_age() == pytest.approx(esperado, abs=5)


@pytest.mark.django_db
def test_login_mostra_manter_conectado_e_nao_oferece_recuperar_senha(client):
    html = client.get(_LOGIN_URL).content.decode()
    assert 'name="manter_conectado"' in html
    assert "senha/esqueci" not in html
    assert 'autocomplete="current-password"' in html


# ---------- Nome e e-mail obrigatórios ----------

def _dados_admin(**extra):
    dados = {
        "username": "novo",
        "first_name": "Novo",
        "last_name": "",
        "email": "novo@exemplo.com",
        "perfil": "financeiro",
        "password1": _SENHA_ADMIN,
        "password2": _SENHA_ADMIN,
    }
    dados.update(extra)
    return dados


@pytest.mark.django_db
def test_cadastro_no_admin_exige_nome_e_email():
    from apps.usuarios.admin import UsuarioCriacaoForm

    assert UsuarioCriacaoForm(_dados_admin()).is_valid()
    sem_nome = UsuarioCriacaoForm(_dados_admin(first_name=""))
    assert not sem_nome.is_valid() and "first_name" in sem_nome.errors
    sem_email = UsuarioCriacaoForm(_dados_admin(email=""))
    assert not sem_email.is_valid() and "email" in sem_email.errors


@pytest.mark.django_db
def test_email_repetido_e_recusado_sem_diferenciar_maiusculas(django_user_model):
    from apps.usuarios.admin import UsuarioCriacaoForm

    django_user_model.objects.create_user("a1", password=_SENHA, email="ana@exemplo.com", first_name="Ana")
    form = UsuarioCriacaoForm(_dados_admin(username="a2", email="ANA@exemplo.com"))
    assert not form.is_valid()
    assert "Já existe um usuário com este e-mail." in form.errors["email"]


@pytest.mark.django_db
def test_editar_o_proprio_usuario_nao_conta_como_email_repetido(django_user_model):
    u = django_user_model.objects.create_user("a3", password=_SENHA, email="bia@exemplo.com", first_name="Bia")
    u.full_clean(exclude=["password"])  # não levanta


@pytest.mark.django_db
def test_nome_aparece_no_lugar_do_login(client, django_user_model):
    django_user_model.objects.create_user(
        "op9", password=_SENHA, email="op9@exemplo.com", first_name="Yslane", last_name="Souza"
    )
    client.post(_LOGIN_URL, {"username": "op9", "password": _SENHA})
    html = client.get(reverse("clientes:lista")).content.decode()
    assert '<span class="user-name">Yslane</span>' in html
    assert ">op9<" not in html
    u = django_user_model.objects.get(username="op9")
    assert str(u) == "Yslane Souza"


@pytest.mark.django_db
def test_conta_antiga_sem_nome_cai_no_login(django_user_model):
    u = django_user_model.objects.create_user("antigo", password=_SENHA)
    assert u.nome_curto == "antigo" and str(u) == "antigo"


# ---------- Modo escuro (botão sol/lua) ----------

@pytest.mark.django_db
def test_botao_de_tema_no_login_e_no_sistema(client, django_user_model):
    login = client.get(_LOGIN_URL).content.decode()
    assert "data-tema-toggle" in login and "js/tema.js" in login
    assert 'class="icone-sol"' in login and 'class="icone-lua"' in login

    django_user_model.objects.create_user("tm", password=_SENHA, email="tm@exemplo.com", first_name="Tê")
    client.post(_LOGIN_URL, {"username": "tm", "password": _SENHA})
    html = client.get(reverse("clientes:lista")).content.decode()
    assert html.count("data-tema-toggle") == 1  # um só, na barra superior (computador e celular)
    # o script vem no <head>, antes do CSS, para não piscar o tema errado
    assert html.index("js/tema.js") < html.index("css/base.css")


# ---------- Tema salvo na conta ----------

@pytest.fixture
def logado(client, django_user_model):
    u = django_user_model.objects.create_user("tp", password=_SENHA, email="tp@exemplo.com", first_name="Teo")
    client.post(_LOGIN_URL, {"username": "tp", "password": _SENHA})
    return u


@pytest.mark.django_db
def test_tema_padrao_e_claro(client, logado):
    html = client.get(reverse("clientes:lista")).content.decode()
    assert 'data-tema="escuro"' not in html
    assert f'data-tema-url="{reverse("usuarios:tema")}"' in html


@pytest.mark.django_db
def test_escolher_escuro_grava_na_conta_e_vale_no_proximo_acesso(client, logado):
    resp = client.post(reverse("usuarios:tema"), {"tema": "escuro"})
    assert resp.status_code == 204
    logado.refresh_from_db()
    assert logado.tema == "escuro"

    # "outro aparelho": sessão nova, sem nada guardado no navegador
    from django.test import Client
    outro = Client()
    outro.post(_LOGIN_URL, {"username": "tp", "password": _SENHA})
    html = outro.get(reverse("clientes:lista")).content.decode()
    assert '<html lang="pt-br" data-tema-url' in html and 'data-tema="escuro"' in html


@pytest.mark.django_db
def test_voltar_ao_claro_grava_na_conta(client, logado):
    client.post(reverse("usuarios:tema"), {"tema": "escuro"})
    client.post(reverse("usuarios:tema"), {"tema": "claro"})
    logado.refresh_from_db()
    assert logado.tema == "claro"


@pytest.mark.django_db
def test_tema_de_um_usuario_nao_afeta_outro(client, logado, django_user_model):
    outro = django_user_model.objects.create_user("tq", password=_SENHA, email="tq@exemplo.com", first_name="Quê")
    client.post(reverse("usuarios:tema"), {"tema": "escuro"})
    outro.refresh_from_db()
    assert outro.tema == "claro"


@pytest.mark.django_db
def test_tema_invalido_e_recusado(client, logado):
    resp = client.post(reverse("usuarios:tema"), {"tema": "roxo"})
    assert resp.status_code == 400
    logado.refresh_from_db()
    assert logado.tema == "claro"


@pytest.mark.django_db
def test_tema_exige_login_e_post(client, logado):
    from django.test import Client
    anonimo = Client()
    resp = anonimo.post(reverse("usuarios:tema"), {"tema": "escuro"})
    assert resp.status_code == 302 and "/entrar/" in resp.url
    assert client.get(reverse("usuarios:tema")).status_code == 405
