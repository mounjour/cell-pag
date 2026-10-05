import pytest


@pytest.fixture(autouse=True)
def _sem_provedores_externos_reais(settings):
    """Testes nunca devem chamar Evolution/Cora de verdade, seja qual for o .env."""
    settings.WHATSAPP_PROVIDER = "log"
    settings.CORA_PROVIDER = "log"
    settings.ROTINA_HEALTHCHECK_URL = ""
    settings.TERMOS_EXIGIR_ACEITE = False  # o aceite só é exigido nos testes de termos


@pytest.fixture(autouse=True)
def _hash_de_senha_rapido(settings):
    """PBKDF2 custa ~0,5 s por usuário criado; nos testes o hash não importa."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def operador(django_user_model):
    return django_user_model.objects.create_user("op", password="s3nha-forte-123")


@pytest.fixture
def auth_client(client, operador):
    client.force_login(operador)
    return client
