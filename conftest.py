import pytest


@pytest.fixture(autouse=True)
def _sem_provedores_externos_reais(settings):
    """Testes nunca devem chamar Evolution/Cora de verdade, seja qual for o .env."""
    settings.WHATSAPP_PROVIDER = "log"
    settings.CORA_PROVIDER = "log"


@pytest.fixture
def operador(django_user_model):
    return django_user_model.objects.create_user("op", password="s3nha-forte-123")


@pytest.fixture
def auth_client(client, operador):
    client.force_login(operador)
    return client
