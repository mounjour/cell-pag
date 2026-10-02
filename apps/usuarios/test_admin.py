import pytest
from django.urls import reverse


@pytest.fixture
def administrador(client, django_user_model, settings):
    settings.TERMOS_EXIGIR_ACEITE = False
    usuario = django_user_model.objects.create_superuser(
        "admin", email="admin@example.com", password="senha-admin"
    )
    client.force_login(usuario)
    return usuario


@pytest.mark.django_db
def test_admin_abre_usuario_sem_nome_e_troca_senha(client, administrador, django_user_model):
    usuario = django_user_model.objects.create_user(
        "conta-antiga", email="conta@example.com", password="senha-antiga"
    )
    ficha = reverse("admin:usuarios_usuario_change", args=[usuario.pk])
    troca = reverse("admin:auth_user_password_change", args=[usuario.pk])
    resposta = client.get(reverse("admin:usuarios_usuario_changelist"))
    assert f'href="{ficha}">conta-antiga</a>' in resposta.content.decode()
    resposta = client.get(ficha)
    assert f'href="{troca}">Trocar senha</a>' in resposta.content.decode()
    assert "Aceite dos termos" in resposta.content.decode()
    resposta = client.post(troca, {
        "password1": "NovaSenhaForte-2026!", "password2": "NovaSenhaForte-2026!",
    })
    assert resposta.status_code == 302
    usuario.refresh_from_db()
    assert usuario.check_password("NovaSenhaForte-2026!")


@pytest.mark.django_db
def test_desativar_preserva_conta_e_impede_login(client, administrador, django_user_model):
    usuario = django_user_model.objects.create_user("operador", password="senha-operador")
    resposta = client.post(reverse("admin:usuarios_usuario_changelist"), {
        "action": "desativar_acesso", "_selected_action": [usuario.pk], "index": "0",
    })
    assert resposta.status_code == 302
    usuario.refresh_from_db()
    assert not usuario.is_active
    client.logout()
    from django.contrib.auth.backends import ModelBackend
    assert not ModelBackend().user_can_authenticate(usuario)


@pytest.mark.django_db
def test_staff_sem_permissao_nao_troca_senha(client, django_user_model, settings):
    settings.TERMOS_EXIGIR_ACEITE = False
    staff = django_user_model.objects.create_user("staff", is_staff=True)
    usuario = django_user_model.objects.create_user("operador")
    client.force_login(staff)
    resposta = client.get(reverse("admin:auth_user_password_change", args=[usuario.pk]))
    assert resposta.status_code == 403
