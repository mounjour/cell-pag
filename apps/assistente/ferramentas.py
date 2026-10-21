"""Ferramentas que o assistente pode usar.

* **Leitura** (``LEITURA``): consultam o sistema e respondem na hora. Não alteram nada.
* **Escrita** (``ESCRITA``): o assistente só *propõe*. Cada uma tem ``validar`` (confere os dados e monta o
  resumo mostrado à pessoa) e ``executar`` (grava de verdade, só depois do clique em Confirmar).

Tudo reaproveita as mesmas regras e modelos das telas do sistema; nada aqui apaga registros.
"""

import datetime
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.aparelhos.models import BloqueioAparelho
from apps.clientes.models import Cliente
from apps.contratos.models import Contrato
from apps.pagamentos.models import ContatoDeCobranca, Pagamento, Vencimento

logger = logging.getLogger(__name__)

MARCA_ASSISTENTE = "Registrado pelo assistente."


class ErroFerramenta(Exception):
    """Pedido que não pode ser atendido; a mensagem vai para o assistente explicar à pessoa."""


# ── utilidades ────────────────────────────────────────────────────────────────

def _brl(valor) -> str:
    return "R$ " + f"{Decimal(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dinheiro(valor, campo: str, *, minimo: Decimal = Decimal("0.00"), exclusivo: bool = False) -> Decimal:
    try:
        numero = Decimal(str(valor).strip().replace("R$", "").replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise ErroFerramenta(f"O valor de {campo} não é um número válido.")
    numero = numero.quantize(Decimal("0.01"))
    if numero < minimo or (exclusivo and numero == minimo):
        raise ErroFerramenta(f"O valor de {campo} precisa ser {'maior que' if exclusivo else 'pelo menos'} {_brl(minimo)}.")
    return numero


def _data(valor, campo: str, *, padrao=None, permitir_futuro: bool = True, permitir_passado: bool = True):
    if valor in (None, ""):
        return padrao
    try:
        data = datetime.date.fromisoformat(str(valor))
    except ValueError:
        raise ErroFerramenta(f"A data de {campo} precisa estar no formato AAAA-MM-DD.")
    hoje = timezone.localdate()
    if not permitir_futuro and data > hoje:
        raise ErroFerramenta(f"A data de {campo} não pode ser no futuro.")
    if not permitir_passado and data < hoje:
        raise ErroFerramenta(f"A data de {campo} não pode estar no passado.")
    return data


def _contrato(contrato_id) -> Contrato:
    try:
        return Contrato.objects.select_related("cliente").get(pk=int(contrato_id))
    except (Contrato.DoesNotExist, TypeError, ValueError):
        raise ErroFerramenta(f"Não existe contrato com id {contrato_id}. Use buscar_cliente para achar o id certo.")


def _nome_do_contrato(contrato: Contrato) -> str:
    return f"{contrato.cliente.nome} · {contrato.apelido}"


# ── leitura ───────────────────────────────────────────────────────────────────

def buscar_cliente(texto: str = "", **_) -> dict:
    texto = (texto or "").strip()
    if len(texto) < 2:
        raise ErroFerramenta("Informe pelo menos 2 letras do nome do cliente.")
    clientes = Cliente.objects.filter(nome__icontains=texto).order_by("nome")[:8]
    return {"clientes": [
        {
            "cliente_id": c.pk, "nome": c.nome, "ativo": c.ativo,
            "contratos": [
                {"contrato_id": ct.pk, "apelido": ct.apelido, "estrutura": ct.get_estrutura_display(), "status": ct.status}
                for ct in c.contratos.all()
            ],
        }
        for c in clientes
    ], "observacao": "Se houver mais de um cliente com nome parecido, pergunte qual é antes de continuar."}


def consultar_contrato(contrato_id=None, **_) -> dict:
    from apps.pagamentos.agenda import parcelas_a_cobrar

    contrato = _contrato(contrato_id)
    hoje = timezone.localdate()
    a_cobrar = {p.numero: p for p in parcelas_a_cobrar(contrato, hoje)}
    situacao = contrato.situacao_atraso(hoje=hoje)
    parcelas = []
    for v in contrato.vencimentos.all().order_by("numero")[:36]:
        cobranca = a_cobrar.get(v.numero)
        parcelas.append({
            "numero": v.numero, "data_de_cobranca": v.data_vencimento.isoformat(), "status": v.status,
            "previsto": str(v.valor_previsto), "pago": str(v.valor_pago), "saldo": str(v.saldo),
            "juros_hoje": str(cobranca.juros) if cobranca else "0.00",
            "dias_de_atraso": cobranca.dias_atraso if cobranca else 0,
            "total_hoje": str(cobranca.total) if cobranca else str(max(v.saldo, Decimal("0.00"))),
        })
    pagamentos = [
        {"data": p.data_pagamento.isoformat(), "parcela": p.vencimento.numero if p.vencimento_id else None,
         "valor": str(p.valor_pago), "juros": str(p.juros_pago), "forma": p.forma}
        for p in contrato.pagamentos.select_related("vencimento").order_by("-data_pagamento", "-pk")[:8]
    ]
    bloqueio = contrato.bloqueios.filter(desbloqueado_em__isnull=True).first()
    return {
        "contrato_id": contrato.pk, "cliente": contrato.cliente.nome, "apelido": contrato.apelido,
        "estrutura": contrato.get_estrutura_display(), "valor_da_parcela": str(contrato.valor_parcela or ""),
        "numero_de_parcelas": contrato.num_parcelas, "quitado": contrato.quitado,
        "dias_de_atraso": situacao.dias_atraso if situacao else 0,
        "situacao": situacao.status if situacao else None,
        "alertar_bloqueio": situacao.alertar_bloqueio if situacao else False,
        "bloqueado_desde": bloqueio.bloqueado_em.date().isoformat() if bloqueio else None,
        "parcelas": parcelas, "ultimos_pagamentos": pagamentos,
        "hoje": hoje.isoformat(),
    }


def listar_atrasos(**_) -> dict:
    from apps.pagamentos.agenda import montar_agenda_do_dia

    agenda = montar_agenda_do_dia()
    linhas = []
    for linha in agenda["linhas"][:40]:
        ct = linha["contrato"]
        linhas.append({
            "contrato_id": ct.pk, "cliente": ct.cliente.nome, "apelido": ct.apelido,
            "dias_de_atraso": linha["situacao"].dias_atraso, "situacao": linha["situacao"].status,
            "alertar_bloqueio": linha["situacao"].alertar_bloqueio, "vence_hoje": linha["vence_hoje"],
            "a_cobrar": str(linha["a_cobrar"]) if linha["a_cobrar"] is not None else None,
        })
    return {"data": agenda["hoje"].isoformat(), "total": len(agenda["linhas"]), "contratos": linhas}


def proximas_cobrancas(dias=14, **_) -> dict:
    from apps.pagamentos.proximas import proximas_cobrancas as proximas

    try:
        dias = max(1, min(int(dias), 30))
    except (TypeError, ValueError):
        dias = 14
    resultado = proximas(dias)
    return {"dias": dias, "quantidade": resultado["quantidade"], "total": str(resultado["total"]), "dias_com_cobranca": [
        {"data": g["data"].isoformat(), "total": str(g["total"]), "cobrancas": [
            {"contrato_id": i["parcela"].contrato_id, "cliente": i["parcela"].contrato.cliente.nome,
             "parcela": i["parcela"].numero, "valor": str(i["parcela"].saldo)}
            for i in g["itens"]
        ]}
        for g in resultado["grupos"]
    ]}


# ── escrita: registrar pagamento ──────────────────────────────────────────────

def validar_pagamento(p: dict) -> tuple[dict, str, list[str]]:
    contrato = _contrato(p.get("contrato_id"))
    if contrato.quitado:
        raise ErroFerramenta("Este contrato já está quitado.")
    if p.get("parcela_numero") in (None, ""):
        venc = contrato.parcela_em_aberto()
        if venc is None:
            raise ErroFerramenta("Este contrato não tem parcela em aberto.")
    else:
        venc = contrato.vencimentos.filter(numero=p["parcela_numero"]).first()
        if venc is None:
            raise ErroFerramenta(f"O contrato não tem a parcela {p['parcela_numero']}.")
    if venc.status == Vencimento.Status.PAGO or venc.pagamentos.exists():
        raise ErroFerramenta(f"A parcela {venc.numero} já recebeu pagamento. Estornar é com a equipe, pela tela do contrato.")
    valor = _dinheiro(p.get("valor_pago"), "o valor da parcela recebido", exclusivo=True)
    juros = _dinheiro(p.get("juros_pago") or "0", "os juros recebidos")
    forma = p.get("forma") or "pix"
    if forma not in {c for c, _ in Pagamento.Forma.choices}:
        raise ErroFerramenta("A forma de pagamento precisa ser pix, dinheiro ou outro.")
    data = _data(p.get("data_pagamento"), "pagamento", padrao=timezone.localdate(), permitir_futuro=False)
    avisos = []
    if valor > venc.saldo:
        avisos.append(f"O valor passa do saldo da parcela ({_brl(venc.saldo)}): o excedente abate a próxima parcela.")
    if valor < venc.saldo:
        avisos.append(f"O valor é menor que o saldo da parcela ({_brl(venc.saldo)}): o que faltar vai para a próxima parcela.")
    normalizados = {
        "contrato_id": contrato.pk, "parcela_numero": venc.numero, "valor_pago": str(valor), "juros_pago": str(juros),
        "forma": forma, "data_pagamento": data.isoformat(), "observacao": str(p.get("observacao") or "")[:200],
    }
    resumo = (
        f"Registrar pagamento de {_nome_do_contrato(contrato)}: parcela {venc.numero} "
        f"(cobrança de {venc.data_vencimento:%d/%m/%Y}), {_brl(valor)}"
        + (f" + {_brl(juros)} de juros" if juros else "")
        + f", {Pagamento.Forma(forma).label}, em {data:%d/%m/%Y}."
    )
    return normalizados, resumo, avisos


def executar_pagamento(p: dict, usuario) -> str:
    from apps.pagamentos.limpeza import encerrar_cobranca_automatica

    contrato = _contrato(p["contrato_id"])
    with transaction.atomic():
        venc = Vencimento.objects.select_for_update().get(contrato=contrato, numero=p["parcela_numero"])
        if venc.status == Vencimento.Status.PAGO or venc.pagamentos.exists():
            raise ErroFerramenta(f"A parcela {venc.numero} já recebeu pagamento; nada foi gravado.")
        pagamento = Pagamento(
            contrato=contrato, vencimento=venc, data_pagamento=datetime.date.fromisoformat(p["data_pagamento"]),
            valor_pago=Decimal(p["valor_pago"]), juros_pago=Decimal(p["juros_pago"]), forma=p["forma"],
            observacao=(f"{p['observacao']} " if p.get("observacao") else "") + MARCA_ASSISTENTE,
            usuario_baixa=usuario,
        )
        pagamento.registrar()
    try:
        encerrar_cobranca_automatica(pagamento)
    except Exception:  # o pagamento já foi salvo; só registra o problema
        logger.exception("Falha ao encerrar a cobrança automática do pagamento %s", pagamento.pk)
    venc.refresh_from_db()
    return f"Pagamento registrado na parcela {venc.numero}; ela agora está {venc.get_status_display().lower()}."


# ── escrita: anotar contato ───────────────────────────────────────────────────

def validar_contato(p: dict) -> tuple[dict, str, list[str]]:
    contrato = _contrato(p.get("contrato_id"))
    tipo = p.get("tipo") or "whatsapp"
    resultado = p.get("resultado") or "outro"
    if tipo not in {c for c, _ in ContatoDeCobranca.Tipo.choices}:
        raise ErroFerramenta("O tipo de contato precisa ser ligacao, whatsapp, pessoalmente ou outro.")
    if resultado not in {c for c, _ in ContatoDeCobranca.Resultado.choices}:
        raise ErroFerramenta("O resultado precisa ser promessa, sem_resposta, contestou ou outro.")
    promessa = _data(p.get("promessa_para"), "promessa", permitir_passado=False)
    if promessa:
        resultado = "promessa"
    elif resultado == "promessa":
        raise ErroFerramenta("Para registrar uma promessa, informe a data prometida (promessa_para).")
    normalizados = {
        "contrato_id": contrato.pk, "tipo": tipo, "resultado": resultado,
        "promessa_para": promessa.isoformat() if promessa else None, "nota": str(p.get("nota") or "")[:480],
    }
    resumo = (
        f"Anotar contato com {_nome_do_contrato(contrato)}: {ContatoDeCobranca.Tipo(tipo).label.lower()}, "
        f"{ContatoDeCobranca.Resultado(resultado).label.lower()}"
        + (f", prometeu pagar até {promessa:%d/%m/%Y}" if promessa else "")
        + (f". Anotação: {normalizados['nota']}" if normalizados["nota"] else ".")
    )
    return normalizados, resumo, []


def executar_contato(p: dict, usuario) -> str:
    contrato = _contrato(p["contrato_id"])
    ContatoDeCobranca.objects.create(
        contrato=contrato, tipo=p["tipo"], resultado=p["resultado"],
        promessa_para=datetime.date.fromisoformat(p["promessa_para"]) if p["promessa_para"] else None,
        nota=(p["nota"] + " " if p["nota"] else "") + MARCA_ASSISTENTE, autor=usuario,
    )
    return "Contato anotado" + (f"; promessa para {datetime.date.fromisoformat(p['promessa_para']):%d/%m/%Y}." if p["promessa_para"] else ".")


# ── escrita: bloqueio e desbloqueio ───────────────────────────────────────────

def validar_bloqueio(p: dict) -> tuple[dict, str, list[str]]:
    contrato = _contrato(p.get("contrato_id"))
    if contrato.quitado:
        raise ErroFerramenta("Contrato quitado: o aparelho não deve ser bloqueado.")
    if contrato.bloqueios.filter(desbloqueado_em__isnull=True).exists():
        raise ErroFerramenta("Este aparelho já está registrado como bloqueado.")
    obs = str(p.get("observacao") or "")[:180]
    return (
        {"contrato_id": contrato.pk, "observacao": obs},
        f"Registrar que o aparelho de {_nome_do_contrato(contrato)} foi bloqueado" + (f" ({obs})." if obs else "."),
        ["Isto só registra no sistema. O bloqueio do celular em si é feito por vocês (iCloud, MDM…)."],
    )


def executar_bloqueio(p: dict, usuario) -> str:
    from apps.pagamentos import badge

    contrato = _contrato(p["contrato_id"])
    if contrato.bloqueios.filter(desbloqueado_em__isnull=True).exists():
        raise ErroFerramenta("Este aparelho já estava registrado como bloqueado; nada foi gravado.")
    BloqueioAparelho.objects.create(contrato=contrato, bloqueado_por=usuario, observacao=p["observacao"])
    badge.invalidar()
    return "Bloqueio registrado."


def validar_desbloqueio(p: dict) -> tuple[dict, str, list[str]]:
    contrato = _contrato(p.get("contrato_id"))
    if not contrato.bloqueios.filter(desbloqueado_em__isnull=True).exists():
        raise ErroFerramenta("Este aparelho não está registrado como bloqueado.")
    return (
        {"contrato_id": contrato.pk},
        f"Registrar que o aparelho de {_nome_do_contrato(contrato)} foi liberado.",
        ["Isto só registra no sistema. A liberação do celular em si é feita por vocês."],
    )


def executar_desbloqueio(p: dict, usuario) -> str:
    from apps.pagamentos import badge

    contrato = _contrato(p["contrato_id"])
    bloqueio = contrato.bloqueios.filter(desbloqueado_em__isnull=True).first()
    if bloqueio is None:
        raise ErroFerramenta("Este aparelho já estava liberado; nada foi gravado.")
    bloqueio.desbloqueado_em = timezone.now()
    bloqueio.desbloqueado_por = usuario
    bloqueio.save(update_fields=["desbloqueado_em", "desbloqueado_por"])
    badge.invalidar()
    return "Liberação registrada."


# ── catálogo entregue ao Claude ───────────────────────────────────────────────

LEITURA = {
    "buscar_cliente": buscar_cliente,
    "consultar_contrato": consultar_contrato,
    "listar_atrasos": listar_atrasos,
    "proximas_cobrancas": proximas_cobrancas,
}

ESCRITA = {
    "registrar_pagamento": (validar_pagamento, executar_pagamento),
    "anotar_contato": (validar_contato, executar_contato),
    "registrar_bloqueio": (validar_bloqueio, executar_bloqueio),
    "registrar_desbloqueio": (validar_desbloqueio, executar_desbloqueio),
}


def _esquema(propriedades: dict, obrigatorias: list[str]) -> dict:
    return {"type": "object", "properties": propriedades, "required": obrigatorias}


FERRAMENTAS = [
    {"name": "buscar_cliente", "description": "Procura clientes pelo nome (parte do nome) e devolve os contratos de cada um, com os ids. Use sempre antes de consultar ou propor algo para um cliente.",
     "input_schema": _esquema({"texto": {"type": "string", "description": "Parte do nome do cliente."}}, ["texto"])},
    {"name": "consultar_contrato", "description": "Mostra um contrato: parcelas (data de cobrança, previsto, pago, saldo, juros de hoje, total de hoje), últimos pagamentos, atraso e bloqueio. Só leitura.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}}, ["contrato_id"])},
    {"name": "listar_atrasos", "description": "Lista os contratos a cobrar hoje (atrasados ou que vencem hoje), do mais atrasado ao menos, com o valor a cobrar. Só leitura.",
     "input_schema": _esquema({}, [])},
    {"name": "proximas_cobrancas", "description": "Lista as cobranças dos próximos dias, agrupadas por data. Só leitura.",
     "input_schema": _esquema({"dias": {"type": "integer", "description": "De 1 a 30; padrão 14."}}, [])},
    {"name": "registrar_pagamento", "description": "PROPÕE registrar o pagamento de uma parcela. Não grava: a pessoa precisa clicar em Confirmar. valor_pago é o valor da PARCELA recebido (sem os juros); os juros do atraso vão separados em juros_pago. Consulte o contrato antes para usar o saldo e os juros de hoje corretos.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"},
         "parcela_numero": {"type": "integer", "description": "Número da parcela; se omitido, usa a primeira em aberto."},
         "valor_pago": {"type": "string", "description": "Valor da parcela recebido, ex.: 157.50"},
         "juros_pago": {"type": "string", "description": "Juros do atraso recebidos, ex.: 5.00 (0 se não houve)."},
         "forma": {"type": "string", "enum": ["pix", "dinheiro", "outro"]},
         "data_pagamento": {"type": "string", "description": "AAAA-MM-DD; padrão hoje. Não pode ser futura."},
         "observacao": {"type": "string"},
     }, ["contrato_id", "valor_pago"])},
    {"name": "anotar_contato", "description": "PROPÕE anotar um contato de cobrança (ligação, mensagem…), com a promessa de pagamento se houver. Não envia nada ao cliente. Só grava depois que a pessoa confirmar.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"},
         "tipo": {"type": "string", "enum": ["ligacao", "whatsapp", "pessoalmente", "outro"]},
         "resultado": {"type": "string", "enum": ["promessa", "sem_resposta", "contestou", "outro"]},
         "promessa_para": {"type": "string", "description": "AAAA-MM-DD, só se prometeu pagar."},
         "nota": {"type": "string"},
     }, ["contrato_id"])},
    {"name": "registrar_bloqueio", "description": "PROPÕE registrar que o aparelho do contrato foi bloqueado (só o registro; o bloqueio do celular é feito pela equipe). Só grava depois da confirmação.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}, "observacao": {"type": "string", "description": "Como foi bloqueado, ex.: iCloud."}}, ["contrato_id"])},
    {"name": "registrar_desbloqueio", "description": "PROPÕE registrar que o aparelho do contrato foi liberado. Só grava depois da confirmação.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}}, ["contrato_id"])},
]
