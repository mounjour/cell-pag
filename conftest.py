import pytest


@pytest.fixture
def operador(django_user_model):
    return django_user_model.objects.create_user("op", password="s3nha-forte-123")


@pytest.fixture
def auth_client(client, operador):
    client.force_login(operador)
    return client
