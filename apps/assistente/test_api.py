"""Conector do Claude Desktop: chave por pessoa, ferramentas e o registro de tudo o que foi gravado."""

import datetime
import json
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.assistente.models import AcessoApi, OperacaoApi
from apps.contratos.models import Contrato
from apps.contratos.tests import cliente, novo_contrato  # noqa: F401  (cliente é fixture)
from apps.pagamentos.models import Pagamento, Vencimento

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_limpa():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def chave(operador):
    return AcessoApi.criar(operador, "Notebook")[1]


@pytest.fixture
def parcela(cliente):
    ct = novo_contrato(cliente, estrutura=Contrato.Estrutura.MENSAL, valor_parcela="157.50", num_parcelas=3,
                       juros_diario=Decimal("5.00"))
    return Vencimento.objects.create(contrato=ct, numero=1, valor_previsto=Decimal("157.50"),
                                     data_vencimento=timezone.localdate() - datetime.timedelta(days=1))


def _chamar(client, chave, ferramenta, **parametros):
    return client.post(reverse("assistente:api_executar"), json.dumps({"ferramenta": ferramenta, "parametros": parametros}),
                       content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {chave}")


def test_sem_chave_ou_com_chave_ruim_nao_entra(client, operador, chave):
    assert client.get(reverse("assistente:api_ferramentas")).status_code == 401
    assert client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION="Bearer cp_errada").status_code == 401
    AcessoApi.objects.get().revogar()
    assert client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}").status_code == 401


def test_a_chave_nao_fica_guardada_em_texto(operador, chave):
    acesso = AcessoApi.objects.get()
    assert chave not in acesso.chave_hash and acesso.final_da_chave == chave[-4:] and len(acesso.chave_hash) == 64


def test_ferramentas_publicadas_com_resumo_nas_que_gravam(client, chave):
    dados = client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}").json()
    por_nome = {f["name"]: f for f in dados["ferramentas"]}
    assert {"buscar_cliente", "consultar_contrato", "listar_atrasos", "registrar_pagamento"} <= set(por_nome)
    assert por_nome["registrar_pagamento"]["grava"] is True and "resumo" in por_nome["registrar_pagamento"]["input_schema"]["required"]
    assert por_nome["buscar_cliente"]["grava"] is False and "resumo" not in por_nome["buscar_cliente"]["input_schema"]["properties"]


def test_leitura_responde_e_nao_gera_registro_de_operacao(client, chave, cliente, parcela):
    resposta = _chamar(client, chave, "buscar_cliente", texto=cliente.nome[:4])
    assert resposta.status_code == 200 and cliente.nome in resposta.json()["resultado"]
    assert OperacaoApi.objects.count() == 0


def test_gravar_pagamento_pede_resumo_e_registra_quem_fez(client, chave, operador, parcela):
    ct = parcela.contrato
    sem_resumo = _chamar(client, chave, "registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50", juros_pago="5.00", forma="pix")
    assert sem_resumo.status_code == 400 and Pagamento.objects.count() == 0

    ok = _chamar(client, chave, "registrar_pagamento", contrato_id=ct.pk, valor_pago="157.50", juros_pago="5.00", forma="pix",
                 resumo="Roberto Lucas, parcela 1, R$ 157,50 + R$ 5,00 de juros, Pix")
    assert ok.status_code == 200 and ok.json()["gravou"] is True
    pagamento = Pagamento.objects.get()
    assert pagamento.valor_pago == Decimal("157.50") and pagamento.juros_pago == Decimal("5.00") and pagamento.usuario_baixa == operador
    assert "assistente" in pagamento.observacao.lower()
    parcela.refresh_from_db()
    assert parcela.status == "pago"
    assert OperacaoApi.objects.filter(ok=False).count() == 1  # a tentativa sem resumo também fica registrada
    operacao = OperacaoApi.objects.get(ok=True)
    assert operacao.grava and operacao.ok and operacao.usuario == operador and "Roberto" in operacao.parametros["resumo"]


def test_parcela_ja_paga_e_recusada_e_o_erro_fica_registrado(client, chave, parcela):
    Pagamento(contrato=parcela.contrato, vencimento=parcela, data_pagamento=timezone.localdate(), valor_pago=Decimal("157.50"), forma="pix").registrar()
    resposta = _chamar(client, chave, "registrar_pagamento", contrato_id=parcela.contrato.pk, parcela_numero=1, valor_pago="157.50", resumo="de novo")
    assert resposta.status_code == 400 and "já recebeu pagamento" in resposta.json()["erro"]
    assert Pagamento.objects.count() == 1 and OperacaoApi.objects.get().ok is False


def test_ferramenta_desconhecida_e_pedido_invalido(client, chave):
    assert _chamar(client, chave, "apagar_tudo").status_code == 400
    ruim = client.post(reverse("assistente:api_executar"), "isto nao e json", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {chave}")
    assert ruim.status_code == 400


def test_tela_cria_a_chave_e_so_entrega_o_instalador_dela(auth_client, operador, django_user_model):
    resposta = auth_client.post(reverse("assistente:desktop"), {"nome": "Notebook da Yslane"})
    html = resposta.content.decode()
    assert "Baixar o instalador" in html and resposta["Cache-Control"] == "no-store"
    acesso = AcessoApi.objects.get()
    chave_na_pagina = html.split('name="chave" value="')[1].split('"')[0]
    assert chave_na_pagina.startswith("cp_") and AcessoApi.por_chave(chave_na_pagina) == acesso

    arquivo = auth_client.post(reverse("assistente:instalador"), {"chave": chave_na_pagina})
    texto = arquivo.content.decode()
    assert arquivo.status_code == 200 and "Instalar-Claude-Desktop.cmd" in arquivo["Content-Disposition"]
    assert f'set "CHAVE={chave_na_pagina}"' in texto and 'set "URL=http' in texto and chr(13) + chr(10) in texto
    assert auth_client.post(reverse("assistente:instalador"), {"chave": "cp_inventada"}).status_code == 400

    # a chave de outra pessoa não vira instalador para quem não é o dono
    outro = django_user_model.objects.create_user("outro3")
    chave_alheia = AcessoApi.criar(outro, "dele")[1]
    assert auth_client.post(reverse("assistente:instalador"), {"chave": chave_alheia}).status_code == 400

    depois = auth_client.get(reverse("assistente:desktop")).content.decode()
    assert 'name="chave"' not in depois and "cp_" not in depois  # a chave não aparece de novo (o botão passa a gerar uma nova)


def test_tela_avisa_com_destaque_para_nunca_usar_sempre_permitir(auth_client):
    html = auth_client.get(reverse("assistente:desktop")).content.decode()
    assert "desktop-alerta" in html and "Permitir uma vez" in html and "Sempre permitir" in html
    assert "revogue a sua chave" in html


def test_arquivos_do_instalador_so_com_chave_valida(client, chave):
    assert AcessoApi.objects.get().ultimo_uso is None
    assert client.get("/assistente/api/conector.py").status_code == 401
    conector = client.get("/assistente/api/conector.py", HTTP_AUTHORIZATION=f"Bearer {chave}")
    instalador = client.get("/assistente/api/instalador.py", HTTP_AUTHORIZATION=f"Bearer {chave}")
    assert conector.status_code == 200 and b"CELULARES_CHAVE" in conector.content
    assert instalador.status_code == 200 and b"def mesclar" in instalador.content
    assert AcessoApi.objects.get().ultimo_uso is None  # baixar o instalador não conta como Claude Desktop conectado


def test_instalador_mescla_a_configuracao_sem_apagar_o_que_ja_existe():
    import importlib.util
    from pathlib import Path

    caminho = Path(__file__).parent / "conector" / "instalar_claude_desktop.py"
    spec = importlib.util.spec_from_file_location("instalar_claude_desktop", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    antes = {"theme": "dark", "mcpServers": {"outro": {"command": "x"}}}
    depois = modulo.mesclar(antes, "python.exe", "celulares_mcp.py", "https://exemplo.org", "cp_abc")
    assert depois["theme"] == "dark" and depois["mcpServers"]["outro"] == {"command": "x"}
    assert depois["mcpServers"]["celulares"]["env"] == {"CELULARES_URL": "https://exemplo.org", "CELULARES_CHAVE": "cp_abc"}
    assert modulo.mesclar({}, "p", "s", "u", "c")["mcpServers"]["celulares"]["command"] == "p"
    assert "celulares" not in antes["mcpServers"]  # a configuração original não foi alterada


def test_instalador_acha_a_pasta_de_dados_da_versao_da_loja(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    caminho = Path(__file__).parent / "conector" / "instalar_claude_desktop.py"
    spec = importlib.util.spec_from_file_location("instalar_claude_desktop", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    local = tmp_path / "local"
    dados = local / "Claude-Data" / "claude_abc"
    dados.mkdir(parents=True)
    (dados / "claude_desktop_config.json").write_text("{}")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert dados / "claude_desktop_config.json" in modulo.caminhos_de_configuracao()
    assert all(c.parent != tmp_path / "roaming" for c in modulo.caminhos_de_configuracao())


def test_revogar_so_a_propria_chave(auth_client, operador, django_user_model):
    outro = django_user_model.objects.create_user("outro")
    alheia = AcessoApi.criar(outro, "dele")[0]
    propria = AcessoApi.criar(operador, "minha")[0]
    assert auth_client.post(reverse("assistente:revogar", args=[alheia.pk])).status_code == 404
    assert auth_client.post(reverse("assistente:revogar", args=[propria.pk])).status_code == 302
    propria.refresh_from_db()
    assert not propria.ativo


def test_baixar_o_conector(auth_client):
    resposta = auth_client.get(reverse("assistente:conector"))
    assert resposta.status_code == 200 and b"CELULARES_CHAVE" in resposta.content


def test_andamento_fica_salvo_ao_recarregar_e_o_instalador_pode_ser_gerado_de_novo(auth_client, operador):
    # 1) cria a chave, mas "fecha a página" sem baixar o instalador
    auth_client.post(reverse("assistente:desktop"), {"nome": "Meu notebook"})
    html = auth_client.get(reverse("assistente:desktop")).content.decode()
    assert "lt-passo--feito" in html and "Chave criada" in html           # passo 1 continua feito após recarregar
    assert "ainda não foi baixado" in html                                # passo 2 oferece baixar, sem refazer tudo
    antigo = AcessoApi.objects.get()

    # 2) baixa pelo botão salvo: troca a chave (a antiga é revogada) e marca o passo como feito
    arquivo = auth_client.post(reverse("assistente:instalador_novo", args=[antigo.pk]))
    assert arquivo.status_code == 200 and "Instalar-Claude-Desktop.cmd" in arquivo["Content-Disposition"]
    antigo.refresh_from_db()
    assert not antigo.ativo
    novo = AcessoApi.objects.get(revogado_em__isnull=True)
    assert novo.pk != antigo.pk and novo.nome == "Meu notebook" and novo.instalador_baixado_em is not None
    assert f'set "CHAVE=' in arquivo.content.decode() and AcessoApi.por_chave(arquivo.content.decode().split('set "CHAVE=')[1].split('"')[0]) == novo

    # 3) recarrega: passo 2 feito, só uma chave ativa
    html = auth_client.get(reverse("assistente:desktop")).content.decode()
    assert "Instalador baixado" in html and "Baixar o instalador de novo" in html
    assert AcessoApi.objects.filter(revogado_em__isnull=True).count() == 1

    # 4) o uso pelo Claude Desktop conclui o passo 3
    chave = arquivo.content.decode().split('set "CHAVE=')[1].split('"')[0]
    assert auth_client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}").status_code == 200
    assert "Claude Desktop conectado" in auth_client.get(reverse("assistente:desktop")).content.decode()

    # 5) marcar as instruções coladas e ver "Tudo pronto"; desmarcar volta atrás
    auth_client.post(reverse("assistente:instrucoes_coladas"), {"feito": "1"})
    assert "Tudo pronto!" in auth_client.get(reverse("assistente:desktop")).content.decode()
    auth_client.post(reverse("assistente:instrucoes_coladas"), {"feito": "0"})
    assert "Tudo pronto!" not in auth_client.get(reverse("assistente:desktop")).content.decode()


def test_renovar_so_a_propria_chave_e_a_marcacao_das_instrucoes_acompanha_a_nova(auth_client, operador, django_user_model):
    outro = django_user_model.objects.create_user("outro4")
    alheia = AcessoApi.criar(outro, "dele")[0]
    assert auth_client.post(reverse("assistente:instalador_novo", args=[alheia.pk])).status_code == 404
    propria = AcessoApi.criar(operador, "minha")[0]
    auth_client.post(reverse("assistente:instrucoes_coladas"), {"feito": "1"})
    auth_client.post(reverse("assistente:instalador_novo", args=[propria.pk]))
    nova = AcessoApi.objects.get(usuario=operador, revogado_em__isnull=True)
    assert nova.instrucoes_coladas_em is not None  # não precisa colar as instruções de novo


def test_chamada_de_teste_do_instalador_nao_conta_como_claude_conectado(client, chave):
    acesso = AcessoApi.objects.get()
    ok = client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}", HTTP_X_TESTE="1")
    acesso.refresh_from_db()
    assert ok.status_code == 200 and acesso.ultimo_uso is None
    client.get(reverse("assistente:api_ferramentas"), HTTP_AUTHORIZATION=f"Bearer {chave}")
    acesso.refresh_from_db()
    assert acesso.ultimo_uso is not None


def test_com_dois_computadores_basta_uma_chave_ter_sido_usada(auth_client, operador):
    usada = AcessoApi.criar(operador, "Notebook")[0]
    AcessoApi.criar(operador, "Outro dispositivo")  # a chave mais nova ainda não foi usada
    usada.ultimo_uso = timezone.now()
    usada.save(update_fields=["ultimo_uso"])
    assert "Claude Desktop conectado" in auth_client.get(reverse("assistente:desktop")).content.decode()


def _pix_no_extrato(cliente, valor, **extra):
    from apps.pagamentos.models import RecebimentoCora

    return RecebimentoCora.objects.create(entrada_id="ext-1", valor=Decimal(valor), recebido_em=timezone.now(), documento=cliente.cpf, nome=cliente.nome, **extra)


def test_pagamento_pix_pelo_chat_liga_a_entrada_do_extrato_e_o_desfazer_devolve(client, auth_client, chave, operador, cliente, parcela):
    from apps.pagamentos.models import RecebimentoCora

    entrada = _pix_no_extrato(cliente, "162.50")
    resposta = _chamar(client, chave, "registrar_pagamento", contrato_id=parcela.contrato.pk, valor_pago="157.50", juros_pago="5.00",
                       forma="pix", resumo="parcela 1 Pix")
    assert "Pix correspondente" in resposta.json()["resultado"]
    entrada.refresh_from_db()
    assert entrada.situacao == RecebimentoCora.Situacao.VINCULADO and entrada.pagamento_id == Pagamento.objects.get().pk

    operacao = OperacaoApi.objects.get(ok=True)
    assert operacao.referencias == {"pagamento_id": Pagamento.objects.get().pk}
    assert "Desfazer" in auth_client.get(reverse("assistente:desktop")).content.decode()

    assert auth_client.post(reverse("assistente:desfazer", args=[operacao.pk])).status_code == 302
    assert Pagamento.objects.count() == 0
    parcela.refresh_from_db(); entrada.refresh_from_db(); operacao.refresh_from_db()
    assert parcela.status != "pago" and entrada.situacao == RecebimentoCora.Situacao.NOVO and entrada.pagamento_id is None
    assert operacao.desfeita_em is not None
    # segunda vez não faz nada nem quebra
    assert auth_client.post(reverse("assistente:desfazer", args=[operacao.pk])).status_code == 302


def test_pagamento_em_dinheiro_nao_mexe_na_entrada_do_extrato(client, chave, cliente, parcela):
    from apps.pagamentos.models import RecebimentoCora

    entrada = _pix_no_extrato(cliente, "162.50")
    _chamar(client, chave, "registrar_pagamento", contrato_id=parcela.contrato.pk, valor_pago="157.50", juros_pago="5.00", forma="dinheiro", resumo="dinheiro")
    entrada.refresh_from_db()
    assert entrada.situacao == RecebimentoCora.Situacao.NOVO


def test_so_quem_gravou_pode_desfazer(client, auth_client, chave, django_user_model, parcela):
    _chamar(client, chave, "registrar_pagamento", contrato_id=parcela.contrato.pk, valor_pago="157.50", juros_pago="5.00", forma="pix", resumo="x")
    operacao = OperacaoApi.objects.get(ok=True)
    outro = django_user_model.objects.create_user("outro")
    client.force_login(outro)
    assert client.post(reverse("assistente:desfazer", args=[operacao.pk])).status_code == 404
    assert Pagamento.objects.count() == 1
