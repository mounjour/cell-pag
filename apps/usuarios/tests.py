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
