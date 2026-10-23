"""Texto do erro quando a Evolution recusa um envio."""

import io
import json
import urllib.error

import pytest
from django.test import override_settings

from apps.pagamentos import whatsapp


def _recusa(monkeypatch, codigo, corpo):
    def falha(*args, **kwargs):
        raise urllib.error.HTTPError("http://evolution", codigo, "x", {}, io.BytesIO(corpo.encode()))

    monkeypatch.setattr(whatsapp.urllib.request, "urlopen", falha)


@override_settings(EVOLUTION_API_URL="http://evolution", EVOLUTION_API_KEY="k", EVOLUTION_INSTANCE="i", WHATSAPP_PROVIDER="evolution")
def test_numero_sem_whatsapp_vira_mensagem_clara(monkeypatch):
    corpo = json.dumps({"status": 400, "response": {"message": [{"jid": "5588999999999@s.whatsapp.net", "exists": False, "number": "5588999999999"}]}})
    _recusa(monkeypatch, 400, corpo)
    with pytest.raises(whatsapp.WhatsAppErro) as erro:
        whatsapp.enviar_mensagem(destinatario="5588999999999", texto="oi")
    assert "HTTP 400" in str(erro.value) and "não tem WhatsApp" in str(erro.value)
    assert "5588999999999" not in str(erro.value)  # o número não vai para a observação


@override_settings(EVOLUTION_API_URL="http://evolution", EVOLUTION_API_KEY="k", EVOLUTION_INSTANCE="i", WHATSAPP_PROVIDER="evolution")
def test_outro_motivo_aparece_e_corpo_ilegivel_nao_quebra(monkeypatch):
    _recusa(monkeypatch, 500, json.dumps({"error": "Internal Server Error", "response": {"message": "Connection Closed"}}))
    with pytest.raises(whatsapp.WhatsAppErro) as erro:
        whatsapp.enviar_mensagem(destinatario="5588999999999", texto="oi")
    assert "HTTP 500" in str(erro.value) and "Connection Closed" in str(erro.value)

    _recusa(monkeypatch, 502, "<html>bad gateway</html>")
    with pytest.raises(whatsapp.WhatsAppErro) as erro:
        whatsapp.enviar_mensagem(destinatario="5588999999999", texto="oi")
    assert str(erro.value) == "A Evolution recusou a operação (HTTP 502)."
