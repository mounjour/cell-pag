import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
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
