"""Saúde das rotinas: cada comando agendado deixa o registro da execução e a tela avisa quando algo parou."""

import datetime

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.pagamentos import rotinas
from apps.pagamentos.models import ExecucaoRotina

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


def test_registrar_marca_sucesso_e_erro():
    with rotinas.registrar("conferir_recebidos"):
        pass
    ok = ExecucaoRotina.objects.get(nome="conferir_recebidos")
    assert ok.sucesso is True and ok.terminada_em is not None

    with pytest.raises(RuntimeError):
        with rotinas.registrar("gerar_vencimentos"):
            raise RuntimeError("a Cora caiu")
    falha = ExecucaoRotina.objects.get(nome="gerar_vencimentos")
    assert falha.sucesso is False and "a Cora caiu" in falha.erro


def test_estados_ok_atrasada_falhou_e_sem_registro():
    agora = timezone.now()
    ExecucaoRotina.objects.create(nome="rotina_diaria", iniciada_em=agora - datetime.timedelta(hours=3), terminada_em=agora, sucesso=True)
    ExecucaoRotina.objects.create(nome="conferir_recebidos", iniciada_em=agora - datetime.timedelta(hours=5),
                                  terminada_em=agora - datetime.timedelta(hours=5), sucesso=True)  # limite de 2h
    ExecucaoRotina.objects.create(nome="gerar_vencimentos", iniciada_em=agora, terminada_em=agora, sucesso=False, erro="x")
    estados = {l["nome"]: l["estado"] for l in rotinas.situacao_das_rotinas(agora)}
    assert estados["rotina_diaria"] == "ok"
    assert estados["conferir_recebidos"] == "atrasada"
    assert estados["gerar_vencimentos"] == "falhou"
    assert estados["enviar_lembrete_diario"] == "sem_registro"
    assert rotinas.rotinas_com_problema() == 2


def test_comando_agendado_deixa_registro(settings):
    settings.CORA_PROVIDER = "log"
    call_command("conferir_recebidos")
    assert ExecucaoRotina.objects.filter(nome="conferir_recebidos", sucesso=True).exists()


def test_pagina_mostra_problema_e_versao(auth_client, settings, monkeypatch):
    agora = timezone.now()
    ExecucaoRotina.objects.create(nome="rotina_diaria", iniciada_em=agora, terminada_em=agora, sucesso=False, erro="falhou a Cora")
    settings.VERSAO_PUBLICADA = "abc1234"
    monkeypatch.setattr(rotinas, "cache", cache)
    cache.set("versao_main_github", "def5678" + "0" * 33, 60)
    html = auth_client.get(reverse("pagamentos:rotinas")).content.decode()
    assert "Falhou" in html and "falhou a Cora" in html and "Atrás da main" in html and "com problema" in html
    # o sino do menu também avisa
    assert "agendada com problema" in auth_client.get(reverse("pagamentos:conexoes")).content.decode()
