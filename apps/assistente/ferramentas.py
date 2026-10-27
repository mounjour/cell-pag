"""Ferramentas que o assistente pode usar.

* **Leitura** (``LEITURA``): consultam o sistema e respondem na hora. Não alteram nada.
* **Escrita** (``ESCRITA``): cada uma tem ``validar`` (confere os dados e monta o resumo) e ``executar``
  (grava). Quem autoriza é a pessoa, no pedido de permissão do Claude Desktop, antes da chamada chegar aqui.

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
            "previsto": str(v.valor_previsto), "ajuste": str(v.acrescimo), "pago": str(v.valor_pago), "saldo": str(v.saldo),
            "juros_hoje": str(cobranca.juros) if cobranca else "0.00",
            "dias_de_atraso": cobranca.dias_atraso if cobranca else 0,
            "total_hoje": str(cobranca.total) if cobranca else str(max(v.saldo, Decimal("0.00"))),
        })
    pagamentos = [
        {"pagamento_id": p.pk, "data": p.data_pagamento.isoformat(), "parcela": p.vencimento.numero if p.vencimento_id else None,
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
        "acordos": [
            {"acordo_id": a.pk, "parcela": a.vencimento.numero, "tipo": a.get_tipo_display(),
             "juros_perdoados": str(a.juros_perdoados), "nova_data": a.nova_data.isoformat() if a.nova_data else None}
            for a in contrato.acordos.select_related("vencimento").filter(desfeito_em__isnull=True).order_by("-criado_em")[:8]
        ],
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
    if venc.status == Vencimento.Status.PAGO:
        raise ErroFerramenta(f"A parcela {venc.numero} já está paga. Se foi lançada errado, use estornar_pagamento.")
    valor = _dinheiro(p.get("valor_pago"), "o valor da parcela recebido", exclusivo=True)
    juros = _dinheiro(p.get("juros_pago") or "0", "os juros recebidos")
    forma = p.get("forma") or "pix"
    if forma not in {c for c, _ in Pagamento.Forma.choices}:
        raise ErroFerramenta("A forma de pagamento precisa ser pix, dinheiro ou outro.")
    data = _data(p.get("data_pagamento"), "pagamento", padrao=timezone.localdate(), permitir_futuro=False)
    avisos = []
    if venc.pagamentos.exists():
        avisos.append("Esta parcela já tinha pagamento parcial; este soma ao que já foi pago.")
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


def executar_pagamento(p: dict, usuario) -> tuple[str, dict]:
    from apps.pagamentos.limpeza import encerrar_cobranca_automatica
    from apps.pagamentos.recebidos import ligar_entrada_ao_pagamento

    contrato = _contrato(p["contrato_id"])
    with transaction.atomic():
        venc = Vencimento.objects.select_for_update().get(contrato=contrato, numero=p["parcela_numero"])
        if venc.status == Vencimento.Status.PAGO:
            raise ErroFerramenta(f"A parcela {venc.numero} já está paga; nada foi gravado.")
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
    ligado = None
    try:
        ligado = ligar_entrada_ao_pagamento(pagamento, usuario)
    except Exception:  # o pagamento já foi salvo; a entrada fica na lista do painel Pix
        logger.exception("Falha ao ligar o Pix do extrato ao pagamento %s", pagamento.pk)
    venc.refresh_from_db()
    texto = f"Pagamento registrado na parcela {venc.numero}; ela agora está {venc.get_status_display().lower()}."
    if ligado:
        texto += " O Pix correspondente do extrato da Cora foi marcado como registrado."
    return texto, {"pagamento_id": pagamento.pk}


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


# ── leitura: estoque, relatórios, histórico, pendências do Pix e rotinas ──────

def listar_estoque(**_) -> dict:
    from apps.aparelhos.models import Aparelho

    aparelhos = Aparelho.objects.filter(contrato__isnull=True).order_by("modelo")[:40]
    return {"aparelhos_disponiveis": [{"aparelho_id": a.pk, "modelo": a.modelo, "imei": a.imei or ""} for a in aparelhos],
            "observacao": "Todo contrato novo parte de um aparelho do estoque (aparelho_id)."}


def relatorio_periodo(inicio=None, fim=None, **_) -> dict:
    from apps.relatorios.servicos import montar_relatorio

    hoje = timezone.localdate()
    inicio = _data(inicio, "início", padrao=hoje.replace(day=1))
    fim = _data(fim, "fim", padrao=hoje)
    if fim < inicio:
        raise ErroFerramenta("A data final precisa ser igual ou depois da inicial.")
    if (fim - inicio).days > 366:
        raise ErroFerramenta("Use um período de no máximo um ano.")
    r = montar_relatorio(inicio, fim)
    return {
        "inicio": inicio.isoformat(), "fim": fim.isoformat(),
        "previsto_no_periodo": str(r["total_previsto"]), "recebido": str(r["total_recebido"]), "juros_recebidos": str(r["total_juros"]),
        "recebido_de_parcelas_do_periodo": str(r["recebido_do_periodo"]), "recebido_de_parcelas_atrasadas": str(r["recebido_de_atrasadas"]),
        "recebido_adiantado": str(r["recebido_adiantado"]), "falta_receber_do_periodo": str(r["falta_do_periodo"]),
        "total_em_atraso_no_fim": str(r["total_atrasado"]), "contratos_em_atraso": r["quantidade_atrasados"],
        "quantidade_de_recebimentos": r["quantidade_recebimentos"], "novos_clientes": r["novos_clientes"],
        "contratos_quitados": r["contratos_quitados"],
        "por_forma": [{"forma": f["forma_label"], "total": str(f["total"]), "quantidade": f["quantidade"]} for f in r["por_forma"]],
        "atrasados": [
            {"cliente": v.contrato.cliente.nome, "contrato_id": v.contrato_id, "parcela": v.numero,
             "dias": v.dias_atraso_relatorio, "valor": str(v.valor_em_aberto)}
            for v in r["atrasados"][:30]
        ],
    }


def listar_pagamentos(contrato_id=None, inicio=None, fim=None, **_) -> dict:
    inicio = _data(inicio, "início")
    fim = _data(fim, "fim")
    pagamentos = Pagamento.objects.select_related("contrato__cliente", "vencimento")
    if contrato_id not in (None, ""):
        pagamentos = pagamentos.filter(contrato_id=_contrato(contrato_id).pk)
    if inicio:
        pagamentos = pagamentos.filter(data_pagamento__gte=inicio)
    if fim:
        pagamentos = pagamentos.filter(data_pagamento__lte=fim)
    if not (inicio or fim or contrato_id not in (None, "")):
        pagamentos = pagamentos.filter(data_pagamento__gte=timezone.localdate() - datetime.timedelta(days=7))
    total = pagamentos.count()
    return {"total_de_pagamentos": total, "mostrando": min(total, 40), "pagamentos": [
        {"pagamento_id": p.pk, "data": p.data_pagamento.isoformat(), "cliente": p.contrato.cliente.nome, "contrato_id": p.contrato_id,
         "parcela": p.vencimento.numero if p.vencimento_id else None, "valor": str(p.valor_pago), "juros": str(p.juros_pago), "forma": p.forma}
        for p in pagamentos.order_by("-data_pagamento", "-pk")[:40]
    ], "observacao": "Sem filtros, mostra só os últimos 7 dias."}


def pendencias_pix(**_) -> dict:
    from apps.pagamentos import recebidos
    from apps.pagamentos.models import CobrancaCora, ComprovanteRecebido, ConfiguracaoCobranca

    a_registrar = []
    for r in recebidos.painel()["a_registrar"][:30]:
        a_registrar.append({
            "recebimento_id": r.pk, "valor": str(r.valor), "recebido_em": timezone.localtime(r.recebido_em).strftime("%Y-%m-%d %H:%M"),
            "quem_pagou": r.nome,
            "clientes_provaveis": [
                {"cliente": s["cliente"].nome, "motivo": s["motivo"],
                 "contratos": [{"contrato_id": c.pk, "apelido": c.apelido, "parcela": v.numero, "saldo": str(v.saldo)} for c, v in s["contratos"]]}
                for s in r.sugestoes
            ],
        })
    duplicadas = CobrancaCora.objects.select_related("vencimento__contrato__cliente").filter(duplicada=True, duplicidade_resolvida_em__isnull=True)
    comprovantes = ComprovanteRecebido.objects.select_related("cliente").filter(status=ComprovanteRecebido.Status.AGUARDANDO)
    com_erro = CobrancaCora.objects.select_related("vencimento__contrato__cliente").filter(status=CobrancaCora.Status.ERRO)
    return {
        "cobranca_automatica_pausada": ConfiguracaoCobranca.esta_pausada(),
        "pix_recebidos_sem_pagamento_registrado": a_registrar,
        "pix_pagos_em_duplicidade": [
            {"cobranca_id": c.pk, "cliente": c.vencimento.contrato.cliente.nome, "parcela": c.vencimento.numero, "total_pago": str(c.total_pago)}
            for c in duplicadas[:20]
        ],
        "comprovantes_aguardando_conferencia": [
            {"comprovante_id": c.pk, "cliente": c.cliente.nome, "recebido_em": timezone.localtime(c.recebido_em).strftime("%Y-%m-%d %H:%M")}
            for c in comprovantes[:20]
        ],
        "pix_com_erro": [
            {"cobranca_id": c.pk, "cliente": c.vencimento.contrato.cliente.nome, "parcela": c.vencimento.numero, "erro": c.erro[:160]}
            for c in com_erro[:20]
        ],
    }


def saude_das_rotinas(**_) -> dict:
    from apps.pagamentos import rotinas
    from apps.pagamentos.models import ConfiguracaoCobranca

    def _hora(momento):
        return timezone.localtime(momento).strftime("%Y-%m-%d %H:%M") if momento else None

    return {
        "cobranca_automatica_pausada": ConfiguracaoCobranca.esta_pausada(),
        "rotinas": [
            {"rotina": l["rotulo"], "estado": l["estado"], "ultima_execucao": _hora(l["ultima"].iniciada_em) if l["ultima"] else None,
             "ultima_que_deu_certo": _hora(l["ultima_ok"].terminada_em) if l["ultima_ok"] else None,
             "erro": (l["ultima"].erro[:200] if l["ultima"] and l["ultima"].sucesso is False else "")}
            for l in rotinas.situacao_das_rotinas()
        ],
        "observacao": "estado: ok, falhou, atrasada, travada ou sem_registro.",
    }


# ── escrita: ajustar valor, acordos, estorno e correção de pagamento ──────────

def _parcela(contrato: Contrato, numero) -> Vencimento:
    if numero in (None, ""):
        venc = contrato.parcela_em_aberto()
        if venc is None:
            raise ErroFerramenta("Este contrato não tem parcela em aberto.")
        return venc
    venc = contrato.vencimentos.filter(numero=numero).first()
    if venc is None:
        raise ErroFerramenta(f"O contrato não tem a parcela {numero}.")
    return venc


def validar_ajuste(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos import parcelas

    contrato = _contrato(p.get("contrato_id"))
    venc = _parcela(contrato, p.get("parcela_numero"))
    if motivo := parcelas.motivo_para_nao_editar(venc):
        raise ErroFerramenta(motivo)
    base_atual = parcelas.valor_base(venc)
    base = _dinheiro(p["valor_base"], "o valor da parcela", exclusivo=True) if p.get("valor_base") not in (None, "") else base_atual
    acrescimo = (
        _dinheiro(p["acrescimo"], "o ajuste", minimo=Decimal("-99999999"))
        if p.get("acrescimo") not in (None, "") else venc.acrescimo
    )
    data = _data(p.get("data_vencimento"), "cobrança", padrao=venc.data_vencimento)
    if base + acrescimo <= 0:
        raise ErroFerramenta("O valor da parcela (com o ajuste) precisa ficar maior que zero.")
    if base + acrescimo < venc.valor_pago:
        raise ErroFerramenta(f"A parcela já recebeu {_brl(venc.valor_pago)}; o valor não pode ficar abaixo disso.")
    if (base, acrescimo, data) == (base_atual, venc.acrescimo, venc.data_vencimento):
        raise ErroFerramenta("Nada mudaria: os valores informados são os que a parcela já tem.")
    motivo = str(p.get("motivo") or "")[:120]
    normalizados = {
        "contrato_id": contrato.pk, "parcela_numero": venc.numero, "valor_base": str(base),
        "acrescimo": str(acrescimo), "data_vencimento": data.isoformat(), "motivo": motivo,
    }
    partes = []
    if acrescimo != venc.acrescimo:
        partes.append(f"ajuste de {_brl(venc.acrescimo)} para {_brl(acrescimo)} ({'valor a mais' if acrescimo >= 0 else 'desconto'})")
    if base != base_atual:
        partes.append(f"valor base de {_brl(base_atual)} para {_brl(base)}")
    if data != venc.data_vencimento:
        partes.append(f"cobrança de {venc.data_vencimento:%d/%m/%Y} para {data:%d/%m/%Y}")
    resumo = (
        f"Ajustar a parcela {venc.numero} de {_nome_do_contrato(contrato)}: " + "; ".join(partes)
        + f". Fica em {_brl(base + acrescimo)}."
    )
    return normalizados, resumo, ["O Pix aberto dessa parcela é refeito com o valor novo."]


def executar_ajuste(p: dict, usuario) -> str:
    from apps.pagamentos import parcelas

    contrato = _contrato(p["contrato_id"])
    venc = contrato.vencimentos.get(numero=p["parcela_numero"])
    try:
        avisos = parcelas.editar_parcela(
            venc, data_vencimento=datetime.date.fromisoformat(p["data_vencimento"]), valor_base=Decimal(p["valor_base"]),
            acrescimo=Decimal(p["acrescimo"]), motivo=p["motivo"], autor=usuario,
        )
    except parcelas.ParcelaInvalida as exc:
        raise ErroFerramenta(str(exc))
    venc.refresh_from_db()
    return f"Parcela {venc.numero} atualizada: agora {_brl(venc.valor_previsto)}, cobrança em {venc.data_vencimento:%d/%m/%Y}." + "".join(f" {t}" for _, t in avisos)


def validar_perdao(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos import acordos

    contrato = _contrato(p.get("contrato_id"))
    venc = _parcela(contrato, p.get("parcela_numero"))
    if motivo := acordos.motivo_para_nao_negociar(venc):
        raise ErroFerramenta(motivo)
    cobrado = acordos.juros_a_cobrar(venc, timezone.localdate())
    if cobrado <= 0:
        raise ErroFerramenta("Esta parcela não tem juros para perdoar hoje.")
    juros = _dinheiro(p["juros"], "os juros a perdoar", exclusivo=True) if p.get("juros") not in (None, "") else cobrado
    if juros > cobrado:
        raise ErroFerramenta(f"Só há {_brl(cobrado)} de juros para perdoar hoje.")
    nota = str(p.get("nota") or "")[:200]
    return (
        {"contrato_id": contrato.pk, "parcela_numero": venc.numero, "juros": str(juros), "nota": nota},
        f"Perdoar {_brl(juros)} de juros da parcela {venc.numero} de {_nome_do_contrato(contrato)}"
        + (f" ({nota})." if nota else "."),
        [],
    )


def executar_perdao(p: dict, usuario) -> str:
    from apps.pagamentos import acordos

    venc = _contrato(p["contrato_id"]).vencimentos.get(numero=p["parcela_numero"])
    try:
        acordo, avisos = acordos.aplicar_acordo(
            venc, tipo="perdao_juros", autor=usuario, juros_perdoar=Decimal(p["juros"]), nota=p["nota"] or MARCA_ASSISTENTE,
        )
    except acordos.AcordoInvalido as exc:
        raise ErroFerramenta(str(exc))
    return f"{_brl(acordo.juros_perdoados)} de juros perdoados (acordo {acordo.pk})." + "".join(f" {t}" for _, t in avisos)


def validar_adiamento(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos import acordos

    contrato = _contrato(p.get("contrato_id"))
    venc = _parcela(contrato, p.get("parcela_numero"))
    if motivo := acordos.motivo_para_nao_negociar(venc):
        raise ErroFerramenta(motivo)
    nova = _data(p.get("nova_data"), "nova cobrança", permitir_passado=False)
    if nova is None:
        raise ErroFerramenta("Informe a nova data de cobrança (nova_data).")
    if nova <= venc.data_vencimento:
        raise ErroFerramenta("A nova data precisa ser depois da cobrança atual da parcela.")
    nota = str(p.get("nota") or "")[:200]
    return (
        {"contrato_id": contrato.pk, "parcela_numero": venc.numero, "nova_data": nova.isoformat(), "nota": nota},
        f"Adiar a parcela {venc.numero} de {_nome_do_contrato(contrato)} de {venc.data_vencimento:%d/%m/%Y} para {nova:%d/%m/%Y}"
        + (f" ({nota})." if nota else "."),
        ["Os juros do atraso recomeçam a contar da nova data."],
    )


def executar_adiamento(p: dict, usuario) -> str:
    from apps.pagamentos import acordos

    venc = _contrato(p["contrato_id"]).vencimentos.get(numero=p["parcela_numero"])
    try:
        acordo, avisos = acordos.aplicar_acordo(
            venc, tipo="nova_data", autor=usuario, nova_data=datetime.date.fromisoformat(p["nova_data"]),
            nota=p["nota"] or MARCA_ASSISTENTE,
        )
    except acordos.AcordoInvalido as exc:
        raise ErroFerramenta(str(exc))
    return f"Parcela {venc.numero} agora é cobrada em {acordo.nova_data:%d/%m/%Y} (acordo {acordo.pk})." + "".join(f" {t}" for _, t in avisos)


def validar_desfazer_acordo(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos import acordos
    from apps.pagamentos.models import Acordo

    acordo = Acordo.objects.select_related("contrato__cliente", "vencimento").filter(pk=p.get("acordo_id")).first()
    if acordo is None:
        raise ErroFerramenta("Não existe acordo com esse id. Use consultar_contrato para ver os acordos.")
    if not acordos.pode_desfazer(acordo):
        raise ErroFerramenta("Este acordo não pode ser desfeito (já foi desfeito, a parcela recebeu pagamento ou há um acordo mais novo).")
    return (
        {"acordo_id": acordo.pk},
        f"Desfazer o acordo ({acordo.get_tipo_display().lower()}) da parcela {acordo.vencimento.numero} de {_nome_do_contrato(acordo.contrato)}.",
        [],
    )


def executar_desfazer_acordo(p: dict, usuario) -> str:
    from apps.pagamentos import acordos
    from apps.pagamentos.models import Acordo

    try:
        avisos = acordos.desfazer_acordo(Acordo.objects.get(pk=p["acordo_id"]), autor=usuario)
    except acordos.AcordoInvalido as exc:
        raise ErroFerramenta(str(exc))
    return "Acordo desfeito: a parcela voltou ao que era antes." + "".join(f" {t}" for _, t in avisos)


def _pagamento(pagamento_id) -> Pagamento:
    try:
        return Pagamento.objects.select_related("contrato__cliente", "vencimento").get(pk=int(pagamento_id))
    except (Pagamento.DoesNotExist, TypeError, ValueError):
        raise ErroFerramenta("Não existe pagamento com esse id. Use consultar_contrato para ver os pagamentos.")


def validar_estorno(p: dict) -> tuple[dict, str, list[str]]:
    pagamento = _pagamento(p.get("pagamento_id"))
    parcela = f"parcela {pagamento.vencimento.numero}" if pagamento.vencimento_id else "sem parcela"
    return (
        {"pagamento_id": pagamento.pk},
        f"Estornar o pagamento de {_brl(pagamento.valor_pago)} de {_nome_do_contrato(pagamento.contrato)} "
        f"({parcela}, {pagamento.data_pagamento:%d/%m/%Y}). A parcela volta a ficar em aberto.",
        ["Se o pagamento veio de um Pix do extrato, ele volta para \"A registrar\"."],
    )


def executar_estorno(p: dict, usuario) -> str:
    from apps.pagamentos.recebidos import estornar_liberando_extrato

    with transaction.atomic():
        pagamento = _pagamento(p["pagamento_id"])
        restante = estornar_liberando_extrato(pagamento)
    texto = "Pagamento estornado; a parcela voltou ao que era."
    if restante:
        texto += " Atenção: essa baixa tinha transportado saldo para parcelas seguintes; confira os valores previstos delas."
    return texto


def validar_edicao_pagamento(p: dict) -> tuple[dict, str, list[str]]:
    pagamento = _pagamento(p.get("pagamento_id"))
    data = _data(p.get("data_pagamento"), "pagamento", padrao=pagamento.data_pagamento, permitir_futuro=False)
    juros = _dinheiro(p["juros_pago"], "os juros recebidos") if p.get("juros_pago") not in (None, "") else pagamento.juros_pago
    forma = p.get("forma") or pagamento.forma
    if forma not in {c for c, _ in Pagamento.Forma.choices}:
        raise ErroFerramenta("A forma de pagamento precisa ser pix, dinheiro ou outro.")
    observacao = str(p["observacao"])[:200] if p.get("observacao") not in (None, "") else pagamento.observacao
    if (data, juros, forma, observacao) == (pagamento.data_pagamento, pagamento.juros_pago, pagamento.forma, pagamento.observacao):
        raise ErroFerramenta("Nada mudaria: os dados informados são os que o pagamento já tem.")
    return (
        {"pagamento_id": pagamento.pk, "data_pagamento": data.isoformat(), "juros_pago": str(juros), "forma": forma, "observacao": observacao},
        f"Corrigir o pagamento de {_nome_do_contrato(pagamento.contrato)}: data {data:%d/%m/%Y}, juros {_brl(juros)}, {Pagamento.Forma(forma).label}.",
        ["O valor da parcela paga não muda aqui; para isso, estorne e registre de novo."],
    )


def executar_edicao_pagamento(p: dict, usuario) -> str:
    pagamento = _pagamento(p["pagamento_id"])
    pagamento.data_pagamento = datetime.date.fromisoformat(p["data_pagamento"])
    pagamento.juros_pago = Decimal(p["juros_pago"])
    pagamento.forma = p["forma"]
    pagamento.observacao = p["observacao"]
    pagamento.save(update_fields=["data_pagamento", "juros_pago", "forma", "observacao"])
    return "Pagamento corrigido."


# ── escrita: clientes ─────────────────────────────────────────────────────────

def _erros_do_formulario(form) -> str:
    return " ".join(f"{', '.join(e)}" if campo == "__all__" else f"{campo}: {', '.join(e)}" for campo, e in form.errors.items())


def _cliente(cliente_id) -> Cliente:
    try:
        return Cliente.objects.get(pk=int(cliente_id))
    except (Cliente.DoesNotExist, TypeError, ValueError):
        raise ErroFerramenta(f"Não existe cliente com id {cliente_id}. Use buscar_cliente.")


def _form_cliente(dados: dict, instancia=None):
    from apps.clientes.forms import ClienteForm

    form = ClienteForm({"nome": dados["nome"], "cpf": dados["cpf"], "telefone_whatsapp": dados["telefone"], "endereco": dados.get("endereco", "")},
                       instance=instancia)
    if not form.is_valid():
        raise ErroFerramenta("Dados do cliente inválidos: " + _erros_do_formulario(form))
    return form


def validar_cliente_novo(p: dict) -> tuple[dict, str, list[str]]:
    dados = {"nome": str(p.get("nome") or "").strip(), "cpf": str(p.get("cpf") or ""), "telefone": str(p.get("telefone") or ""),
             "endereco": str(p.get("endereco") or "").strip()}
    form = _form_cliente(dados)
    c = form.cleaned_data
    return dados, f"Cadastrar o cliente {c['nome']} (CPF {c['cpf'][:3]}.***.***-{c['cpf'][-2:]}, WhatsApp {c['telefone_whatsapp']}).", []


def executar_cliente_novo(p: dict, usuario) -> tuple[str, dict]:
    cliente = _form_cliente(p).save()
    return f"Cliente cadastrado (id {cliente.pk}).", {"cliente_id": cliente.pk}


def validar_cliente_edicao(p: dict) -> tuple[dict, str, list[str]]:
    cliente = _cliente(p.get("cliente_id"))
    dados = {
        "cliente_id": cliente.pk,
        "nome": str(p["nome"]).strip() if p.get("nome") else cliente.nome,
        "cpf": str(p["cpf"]) if p.get("cpf") else cliente.cpf,
        "telefone": str(p["telefone"]) if p.get("telefone") else str(cliente.telefone_whatsapp),
        "endereco": str(p["endereco"]).strip() if p.get("endereco") is not None else cliente.endereco,
    }
    form = _form_cliente(dados, cliente)
    if not form.has_changed():
        raise ErroFerramenta("Nada mudaria: os dados informados são os que o cliente já tem.")
    mudou = ", ".join(form.changed_data).replace("telefone_whatsapp", "telefone")
    return dados, f"Atualizar o cadastro de {cliente.nome} ({mudou}).", []


def executar_cliente_edicao(p: dict, usuario) -> str:
    _form_cliente(p, _cliente(p["cliente_id"])).save()
    return "Cadastro atualizado."


def validar_arquivar(p: dict) -> tuple[dict, str, list[str]]:
    cliente = _cliente(p.get("cliente_id"))
    ativo = bool(p.get("ativo", False))
    if cliente.ativo == ativo:
        raise ErroFerramenta("Este cliente já está " + ("ativo." if ativo else "arquivado."))
    return ({"cliente_id": cliente.pk, "ativo": ativo},
            f"{'Reativar' if ativo else 'Arquivar'} o cliente {cliente.nome}" + ("." if ativo else " (some da lista principal; o histórico fica)."), [])


def executar_arquivar(p: dict, usuario) -> str:
    cliente = _cliente(p["cliente_id"])
    cliente.ativo = p["ativo"]
    cliente.save(update_fields=["ativo", "atualizado_em"])
    return "Cliente reativado." if p["ativo"] else "Cliente arquivado."


# ── escrita: contratos ────────────────────────────────────────────────────────

def _gerar_parcelas_do_contrato(contrato: Contrato) -> None:
    """Mesmo que a tela faz ao salvar: cria as parcelas que faltam, poda as que passam do total e atualiza o status."""
    if contrato.quitado or contrato.valor_parcela is None:
        return
    contrato.gerar_vencimentos()
    contrato.podar_vencimentos_excedentes()
    contrato.atualizar_data_prevista_quitacao()
    contrato.sincronizar_status()


def _texto_form(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return f"{valor:.2f}".replace(".", ",")
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return str(valor)


def _form_contrato(dados: dict, instancia=None):
    from apps.contratos.forms import ContratoForm

    form = ContratoForm(dados, instance=instancia)
    if not form.is_valid():
        raise ErroFerramenta("Dados do contrato inválidos: " + _erros_do_formulario(form))
    return form


def validar_contrato_novo(p: dict) -> tuple[dict, str, list[str]]:
    cliente = _cliente(p.get("cliente_id"))
    if not cliente.ativo:
        raise ErroFerramenta("Este cliente está arquivado; reative-o antes.")
    dados = {
        "cliente": str(cliente.pk), "aparelho": _texto_form(p.get("aparelho_id")), "apelido": str(p.get("apelido") or "").strip(),
        "valor_total": _texto_form(p.get("valor_total")), "num_parcelas": _texto_form(p.get("num_parcelas")),
        "estrutura": str(p.get("estrutura") or ""), "data_inicio": _texto_form(p.get("data_inicio") or timezone.localdate()),
        "primeira_cobranca": _texto_form(p.get("primeira_cobranca")), "juros_diario": _texto_form(p.get("juros_diario") or "5.00"),
        "dia_semana": _texto_form(p.get("dia_semana")), "dia_mes": _texto_form(p.get("dia_mes")), "dia_mes_2": _texto_form(p.get("dia_mes_2")),
        "quinzena": str(p.get("quinzena") or "semana"), "parcelas_ja_pagas": _texto_form(p.get("parcelas_ja_pagas")),
        "entrada": _texto_form(p.get("entrada")), "entrada_forma": str(p.get("entrada_forma") or "dinheiro"),
        "observacoes": str(p.get("observacoes") or "")[:500], "status": Contrato.Status.EM_DIA,
    }
    form = _form_contrato(dados)
    c = form.cleaned_data
    contrato = form.instance
    contrato.atualizar_data_prevista_quitacao(salvar=False)
    avisos = ["Assim que for criado, o contrato entra na cobrança automática (se ela não estiver pausada)."]
    if contrato.parcelas_conferem is False:
        avisos.append(f"Atenção: parcela × quantidade dá {_brl(contrato.total_das_parcelas)}, diferente do total ({_brl(contrato.valor_total)}).")
    if c.get("parcelas_ja_pagas"):
        avisos.append(f"As {c['parcelas_ja_pagas']} primeiras parcelas serão marcadas como pagas na própria data de vencimento.")
    resumo = (
        f"Criar contrato de {cliente.nome}: {c['aparelho']} ({c['apelido']}), {_brl(c['valor_total'])} em {c['num_parcelas']}x de "
        f"{_brl(contrato.valor_parcela)} ({Contrato.Estrutura(c['estrutura']).label.lower()}), compra em {c['data_inicio']:%d/%m/%Y}, "
        f"primeira cobrança em {c['primeira_cobranca']:%d/%m/%Y}, juros {_brl(c['juros_diario'])}/dia"
        + (f", entrada de {_brl(c['entrada'])}" if c.get("entrada") else "") + "."
    )
    return dados, resumo, avisos


def executar_contrato_novo(p: dict, usuario) -> tuple[str, dict]:
    from apps.contratos import importacao as importacao_contratos

    with transaction.atomic():
        form = _form_contrato(p)
        quantidade = form.cleaned_data.get("parcelas_ja_pagas") or 0
        contrato = form.save()
        _gerar_parcelas_do_contrato(contrato)
        if quantidade:
            ultima = contrato.data_da_parcela(quantidade)
            contrato.gerar_vencimentos(dias_a_frente=max(60, (ultima - timezone.localdate()).days))
            for venc in contrato.vencimentos.filter(numero__lte=quantidade).exclude(status=Vencimento.Status.PAGO).order_by("numero"):
                Pagamento(contrato=contrato, vencimento=venc, data_pagamento=venc.data_vencimento, valor_pago=venc.saldo if venc.saldo > 0 else venc.valor_previsto,
                          forma=Pagamento.Forma.OUTRO, usuario_baixa=usuario, observacao="Pagamento anterior ao cadastro no sistema. " + MARCA_ASSISTENTE).registrar()
        entrada = form.cleaned_data.get("entrada")
        if entrada:
            Pagamento(contrato=contrato, vencimento=None, data_pagamento=contrato.data_inicio, valor_pago=entrada,
                      forma=form.cleaned_data["entrada_forma"], usuario_baixa=usuario, observacao="Entrada do contrato. " + MARCA_ASSISTENTE).registrar()
        importacao_contratos.resolver_pendencias_do_contrato(contrato)
    return f"Contrato criado (id {contrato.pk}) com {contrato.vencimentos.count()} parcela(s) gerada(s).", {"contrato_id": contrato.pk}


CAMPOS_EDITAVEIS_DO_CONTRATO = ("apelido", "juros_diario", "valor_total", "valor_parcela", "num_parcelas", "estrutura", "data_inicio", "primeira_cobranca", "observacoes")


def validar_contrato_edicao(p: dict) -> tuple[dict, str, list[str]]:
    from apps.contratos.forms import ContratoForm

    contrato = _contrato(p.get("contrato_id"))
    if contrato.quitado:
        raise ErroFerramenta("Contrato quitado: não dá para editar.")
    pedidos = {c: p[c] for c in CAMPOS_EDITAVEIS_DO_CONTRATO if p.get(c) not in (None, "")}
    if not pedidos:
        raise ErroFerramenta("Informe pelo menos um campo para mudar.")
    atual = ContratoForm(instance=contrato)
    dados = {nome: _texto_form(atual.initial.get(nome, getattr(contrato, nome, None))) for nome in atual.fields if nome not in ("entrada", "entrada_forma", "parcelas_ja_pagas")}
    dados.update({c: _texto_form(v) for c, v in pedidos.items()})
    form = _form_contrato(dados, contrato)
    if not form.has_changed():
        raise ErroFerramenta("Nada mudaria: os valores informados são os que o contrato já tem.")
    avisos = ["As parcelas em aberto são atualizadas com os valores e datas novos (o valor a mais de cada parcela é mantido)."]
    if "valor_total" in pedidos or "num_parcelas" in pedidos:
        avisos.append("O valor da parcela é recalculado a partir do total e da quantidade, a não ser que você informe valor_parcela.")
    dados["contrato_id"] = contrato.pk
    return dados, f"Editar o contrato {_nome_do_contrato(contrato)}: " + ", ".join(f"{c} = {v}" for c, v in pedidos.items()) + ".", avisos


def executar_contrato_edicao(p: dict, usuario) -> str:
    from apps.pagamentos.parcelas import ressincronizar_parcelas_em_aberto

    contrato = _contrato(p["contrato_id"])
    dados = {k: v for k, v in p.items() if k != "contrato_id"}
    with transaction.atomic():
        contrato = _form_contrato(dados, contrato).save()
    _gerar_parcelas_do_contrato(contrato)
    n = ressincronizar_parcelas_em_aberto(contrato)
    return "Contrato atualizado." + (f" {n} parcela(s) em aberto atualizada(s)." if n else "")


def validar_quitar(p: dict) -> tuple[dict, str, list[str]]:
    contrato = _contrato(p.get("contrato_id"))
    if contrato.quitado:
        raise ErroFerramenta("Este contrato já está quitado.")
    abertas = contrato.vencimentos.exclude(status=Vencimento.Status.PAGO).count()
    avisos = [f"Ainda há {abertas} parcela(s) não paga(s) já geradas; a cobrança automática do contrato para."] if abertas else []
    return {"contrato_id": contrato.pk}, f"Marcar como QUITADO o contrato {_nome_do_contrato(contrato)} (a cobrança para).", avisos


def executar_quitar(p: dict, usuario) -> str:
    contrato = _contrato(p["contrato_id"])
    if contrato.quitado:
        raise ErroFerramenta("Este contrato já estava quitado; nada foi gravado.")
    contrato.status = Contrato.Status.QUITADO
    contrato.quitado_em = timezone.localdate()
    contrato.save(update_fields=["status", "quitado_em", "atualizado_em"])
    contrato.atualizar_data_prevista_quitacao()
    return "Contrato quitado. A cobrança para aqui."


# ── escrita: cobrança automática, Pix, extrato e comprovantes ────────────────

def validar_cobranca_automatica(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos.models import ConfiguracaoCobranca

    acao = p.get("acao")
    if acao not in ("pausar", "retomar"):
        raise ErroFerramenta("A ação precisa ser pausar ou retomar.")
    config = ConfiguracaoCobranca.obter()
    if acao == "pausar":
        if config.pausada:
            raise ErroFerramenta("As cobranças automáticas já estão pausadas.")
        return {"acao": acao}, "PAUSAR as cobranças automáticas de todo o sistema (nenhuma mensagem nem Pix sai até retomar).", []
    if config.nunca_iniciada:
        raise ErroFerramenta("As cobranças nunca foram iniciadas: o primeiro começo exige conferência na tela Cobrar hoje do sistema.")
    if not config.pausada:
        raise ErroFerramenta("As cobranças automáticas já estão ligadas.")
    return {"acao": acao}, "RETOMAR as cobranças automáticas de todo o sistema (a próxima rotina volta a cobrar os clientes).", []


def executar_cobranca_automatica(p: dict, usuario) -> str:
    from apps.pagamentos.models import ConfiguracaoCobranca

    ConfiguracaoCobranca.definir(p["acao"] == "pausar", usuario)
    return "Cobranças automáticas pausadas." if p["acao"] == "pausar" else "Cobranças automáticas retomadas."


ACOES_DO_PIX = {
    "suspender": "Suspender a cobrança automática (cancela o Pix, se houver, e a rotina não cobra mais essa parcela)",
    "cancelar_pix": "Cancelar o Pix (a cobrança automática dessa parcela fica suspensa)",
    "retomar": "Retomar a cobrança automática (um Pix novo sai na próxima rotina)",
    "gerar_pix": "Gerar o Pix da parcela agora",
}


def validar_pix_parcela(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos.models import CobrancaCora

    contrato = _contrato(p.get("contrato_id"))
    acao = p.get("acao")
    if acao not in ACOES_DO_PIX:
        raise ErroFerramenta("A ação precisa ser " + ", ".join(ACOES_DO_PIX) + ".")
    venc = _parcela(contrato, p.get("parcela_numero"))
    if venc.status == Vencimento.Status.PAGO:
        raise ErroFerramenta(f"A parcela {venc.numero} já está paga.")
    pix = CobrancaCora.objects.filter(vencimento=venc).first()
    if acao == "cancelar_pix" and (pix is None or pix.status == CobrancaCora.Status.CANCELADO):
        raise ErroFerramenta("Esta parcela não tem Pix aberto para cancelar.")
    if acao == "retomar" and (pix is None or pix.status != CobrancaCora.Status.CANCELADO):
        raise ErroFerramenta("Esta parcela não está com a cobrança suspensa.")
    if acao == "gerar_pix" and pix is not None and pix.status == CobrancaCora.Status.CANCELADO:
        raise ErroFerramenta("O Pix desta parcela foi cancelado; use a ação retomar primeiro.")
    return ({"contrato_id": contrato.pk, "parcela_numero": venc.numero, "acao": acao},
            f"{ACOES_DO_PIX[acao]}: parcela {venc.numero} de {_nome_do_contrato(contrato)}.",
            ["Nunca cancela um Pix já pago; a Cora é consultada antes."] if acao in ("suspender", "cancelar_pix") else [])


def executar_pix_parcela(p: dict, usuario) -> str:
    from apps.pagamentos import cora_api
    from apps.pagamentos.models import CobrancaCora
    from apps.pagamentos.pix_cora import CancelamentoRecusado, cancelar_cobranca, obter_ou_criar_cobranca, retomar_cobranca, suspender_cobranca

    venc = _contrato(p["contrato_id"]).vencimentos.get(numero=p["parcela_numero"])
    pix = CobrancaCora.objects.filter(vencimento=venc).first()
    try:
        if p["acao"] == "suspender":
            suspender_cobranca(venc)
            return "Cobrança automática da parcela suspensa."
        if p["acao"] == "cancelar_pix":
            cancelar_cobranca(pix, motivo="Cancelado pelo assistente", autor=usuario)
            return "Pix cancelado; a cobrança automática dessa parcela ficou suspensa."
        if p["acao"] == "retomar":
            retomar_cobranca(pix)
            return "Cobrança retomada; o Pix novo sai na próxima rotina."
        novo = obter_ou_criar_cobranca(venc)
        if not novo.pix_copia_e_cola:
            raise ErroFerramenta("O Pix não pôde ser gerado agora" + (f": {novo.erro}" if novo.erro else "."))
        return f"Pix gerado ({novo.get_status_display().lower()}), valor {_brl(novo.valor)}."
    except CancelamentoRecusado as exc:
        raise ErroFerramenta(str(exc))
    except cora_api.CoraErro as exc:
        raise ErroFerramenta(f"A Cora recusou ou não respondeu: {exc} Nada foi alterado.")


def validar_duplicidade(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos.models import CobrancaCora

    c = CobrancaCora.objects.select_related("vencimento__contrato__cliente").filter(pk=p.get("cobranca_id"), duplicada=True).first()
    if c is None:
        raise ErroFerramenta("Não existe Pix duplicado com esse id. Use pendencias_pix.")
    if c.duplicidade_resolvida_em:
        raise ErroFerramenta("Esta duplicidade já foi marcada como resolvida.")
    return ({"cobranca_id": c.pk}, f"Marcar como resolvida a duplicidade de Pix de {c.vencimento.contrato.cliente.nome} (parcela {c.vencimento.numero}; o valor já foi devolvido).",
            ["Isto só marca no sistema. A devolução do dinheiro é feita por vocês na Cora."])


def executar_duplicidade(p: dict, usuario) -> str:
    from apps.pagamentos.models import CobrancaCora

    CobrancaCora.objects.filter(pk=p["cobranca_id"], duplicidade_resolvida_em__isnull=True).update(duplicidade_resolvida_em=timezone.now())
    return "Duplicidade marcada como resolvida."


def _comprovante(comprovante_id):
    from apps.pagamentos.models import ComprovanteRecebido

    c = ComprovanteRecebido.objects.select_related("cliente").filter(pk=comprovante_id).first()
    if c is None or c.status != ComprovanteRecebido.Status.AGUARDANDO:
        raise ErroFerramenta("Não há comprovante aguardando com esse id. Use pendencias_pix.")
    return c


def validar_conferir_comprovante(p: dict) -> tuple[dict, str, list[str]]:
    c = _comprovante(p.get("comprovante_id"))
    return {"comprovante_id": c.pk}, f"Consultar a Cora sobre o comprovante de {c.cliente.nome}.", ["Se o Pix já caiu, a baixa é dada e o cliente é avisado por WhatsApp."]


def executar_conferir_comprovante(p: dict, usuario) -> str:
    from apps.pagamentos.comprovantes import conferir_na_cora
    from apps.pagamentos.models import ComprovanteRecebido

    c = _comprovante(p["comprovante_id"])
    if not conferir_na_cora(c):
        return "Não consegui consultar a Cora (sem Pix gerado ou Cora fora do ar). Confira a conta e, se o dinheiro entrou, registre o pagamento."
    c.refresh_from_db()
    if c.status == ComprovanteRecebido.Status.CONFIRMADO:
        return "Pix confirmado pela Cora: baixa dada e cliente avisado."
    return "O Pix ainda não caiu na Cora."


def validar_descartar_comprovante(p: dict) -> tuple[dict, str, list[str]]:
    c = _comprovante(p.get("comprovante_id"))
    return {"comprovante_id": c.pk}, f"Descartar o aviso de comprovante de {c.cliente.nome} (não era comprovante).", []


def executar_descartar_comprovante(p: dict, usuario) -> str:
    from apps.pagamentos.models import ComprovanteRecebido

    c = _comprovante(p["comprovante_id"])
    c.status, c.resolvido_em, c.resolvido_por = ComprovanteRecebido.Status.DESCARTADO, timezone.now(), usuario
    c.save(update_fields=["status", "resolvido_em", "resolvido_por"])
    return "Aviso descartado."


def _entrada_do_extrato(recebimento_id):
    from apps.pagamentos.models import RecebimentoCora

    r = RecebimentoCora.objects.filter(pk=recebimento_id, situacao=RecebimentoCora.Situacao.NOVO).first()
    if r is None:
        raise ErroFerramenta("Não há entrada do extrato 'a registrar' com esse id. Use pendencias_pix.")
    return r


def validar_ignorar_entrada(p: dict) -> tuple[dict, str, list[str]]:
    r = _entrada_do_extrato(p.get("recebimento_id"))
    return {"recebimento_id": r.pk}, f"Ignorar a entrada de {_brl(r.valor)} de {r.nome or 'quem pagou'} no extrato (não é pagamento de parcela).", []


def executar_ignorar_entrada(p: dict, usuario) -> str:
    from apps.pagamentos import recebidos

    _entrada_do_extrato(p["recebimento_id"])
    recebidos.ignorar(p["recebimento_id"], usuario)
    return "Entrada ignorada."


def validar_vincular_entrada(p: dict) -> tuple[dict, str, list[str]]:
    r = _entrada_do_extrato(p.get("recebimento_id"))
    pagamento = _pagamento(p.get("pagamento_id"))
    if pagamento.recebimentos_cora.exists():
        raise ErroFerramenta("Este pagamento já está ligado a uma entrada do extrato.")
    avisos = []
    if pagamento.valor_pago + pagamento.juros_pago != r.valor:
        avisos.append(f"O valor do pagamento ({_brl(pagamento.valor_pago + pagamento.juros_pago)}) é diferente do da entrada ({_brl(r.valor)}).")
    return ({"recebimento_id": r.pk, "pagamento_id": pagamento.pk},
            f"Ligar a entrada de {_brl(r.valor)} do extrato ao pagamento de {_nome_do_contrato(pagamento.contrato)} ({pagamento.data_pagamento:%d/%m/%Y}).", avisos)


def executar_vincular_entrada(p: dict, usuario) -> str:
    from apps.pagamentos import recebidos

    _entrada_do_extrato(p["recebimento_id"])
    recebidos.vincular(p["recebimento_id"], _pagamento(p["pagamento_id"]), usuario)
    return "Entrada do extrato ligada ao pagamento."


def validar_enviar_cobranca(p: dict) -> tuple[dict, str, list[str]]:
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.whatsapp import mascara_numero

    contrato = _contrato(p.get("contrato_id"))
    if contrato.quitado:
        raise ErroFerramenta("Contrato quitado: não há o que cobrar.")
    hoje = timezone.localdate()
    ja = Cobranca.objects.filter(contrato=contrato, data_alvo=hoje, canal=Cobranca.Canal.WHATSAPP,
                                 status__in=[Cobranca.Status.ENVIADO, Cobranca.Status.ENTREGUE, Cobranca.Status.LIDO]).exists()
    if ja:
        raise ErroFerramenta("A cobrança de hoje deste contrato já foi enviada.")
    return ({"contrato_id": contrato.pk},
            f"Enviar AGORA no WhatsApp de {contrato.cliente.nome} ({mascara_numero(contrato.cliente.telefone_whatsapp)}) a cobrança de hoje, com o Pix, igual à da rotina automática.",
            ["Isto envia uma mensagem de verdade ao cliente. Só sai se o contrato estiver na cobrança de hoje (atrasado ou vencendo hoje)."])


def executar_enviar_cobranca(p: dict, usuario) -> str:
    from apps.pagamentos.cobranca import enviar_cobranca_do_contrato
    from apps.pagamentos.models import Cobranca

    resultado = enviar_cobranca_do_contrato(_contrato(p["contrato_id"]))
    cobranca = resultado["cobranca"]
    if cobranca is None:
        raise ErroFerramenta("Este contrato não está na cobrança de hoje (não está atrasado nem vence hoje); nada foi enviado.")
    if resultado["ignoradas"] and cobranca.status not in (Cobranca.Status.ENVIADO,):
        raise ErroFerramenta("Nada foi enviado: a cobrança dessa parcela está suspensa (Pix cancelado) ou já havia saído.")
    if cobranca.status == Cobranca.Status.ERRO:
        raise ErroFerramenta(f"A mensagem não saiu: {cobranca.erro or 'erro no envio'}")
    if resultado["simuladas"]:
        return "Modo de simulação: a mensagem NÃO foi enviada de verdade."
    return "Cobrança enviada no WhatsApp do cliente."


# ── catálogo entregue ao Claude ───────────────────────────────────────────────

LEITURA = {
    "buscar_cliente": buscar_cliente,
    "consultar_contrato": consultar_contrato,
    "listar_atrasos": listar_atrasos,
    "proximas_cobrancas": proximas_cobrancas,
    "listar_estoque": listar_estoque,
    "relatorio_periodo": relatorio_periodo,
    "listar_pagamentos": listar_pagamentos,
    "pendencias_pix": pendencias_pix,
    "saude_das_rotinas": saude_das_rotinas,
}

ESCRITA = {
    "registrar_pagamento": (validar_pagamento, executar_pagamento),
    "anotar_contato": (validar_contato, executar_contato),
    "registrar_bloqueio": (validar_bloqueio, executar_bloqueio),
    "registrar_desbloqueio": (validar_desbloqueio, executar_desbloqueio),
    "ajustar_parcela": (validar_ajuste, executar_ajuste),
    "perdoar_juros": (validar_perdao, executar_perdao),
    "adiar_parcela": (validar_adiamento, executar_adiamento),
    "desfazer_acordo": (validar_desfazer_acordo, executar_desfazer_acordo),
    "estornar_pagamento": (validar_estorno, executar_estorno),
    "corrigir_pagamento": (validar_edicao_pagamento, executar_edicao_pagamento),
    "cadastrar_cliente": (validar_cliente_novo, executar_cliente_novo),
    "editar_cliente": (validar_cliente_edicao, executar_cliente_edicao),
    "arquivar_cliente": (validar_arquivar, executar_arquivar),
    "cadastrar_contrato": (validar_contrato_novo, executar_contrato_novo),
    "editar_contrato": (validar_contrato_edicao, executar_contrato_edicao),
    "quitar_contrato": (validar_quitar, executar_quitar),
    "cobranca_automatica": (validar_cobranca_automatica, executar_cobranca_automatica),
    "controlar_pix_parcela": (validar_pix_parcela, executar_pix_parcela),
    "resolver_duplicidade_pix": (validar_duplicidade, executar_duplicidade),
    "conferir_comprovante": (validar_conferir_comprovante, executar_conferir_comprovante),
    "descartar_comprovante": (validar_descartar_comprovante, executar_descartar_comprovante),
    "ignorar_entrada_extrato": (validar_ignorar_entrada, executar_ignorar_entrada),
    "vincular_entrada_extrato": (validar_vincular_entrada, executar_vincular_entrada),
    "enviar_cobranca_whatsapp": (validar_enviar_cobranca, executar_enviar_cobranca),
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
    {"name": "registrar_pagamento", "description": "REGISTRA manualmente o pagamento de uma parcela (inteiro ou parcial, em qualquer data passada). valor_pago é o valor da PARCELA recebido (sem os juros); os juros do atraso vão separados em juros_pago. Consulte o contrato antes para usar o saldo e os juros de hoje corretos. Para somar ou tirar valor da parcela use ajustar_parcela.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"},
         "parcela_numero": {"type": "integer", "description": "Número da parcela; se omitido, usa a primeira em aberto."},
         "valor_pago": {"type": "string", "description": "Valor da parcela recebido, ex.: 157.50"},
         "juros_pago": {"type": "string", "description": "Juros do atraso recebidos, ex.: 5.00 (0 se não houve)."},
         "forma": {"type": "string", "enum": ["pix", "dinheiro", "outro"]},
         "data_pagamento": {"type": "string", "description": "AAAA-MM-DD; padrão hoje. Não pode ser futura."},
         "observacao": {"type": "string"},
     }, ["contrato_id", "valor_pago"])},
    {"name": "anotar_contato", "description": "ANOTA um contato de cobrança (ligação, mensagem…), com a promessa de pagamento se houver. Não envia nada ao cliente. A pessoa autoriza no pedido de permissão do Claude Desktop.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"},
         "tipo": {"type": "string", "enum": ["ligacao", "whatsapp", "pessoalmente", "outro"]},
         "resultado": {"type": "string", "enum": ["promessa", "sem_resposta", "contestou", "outro"]},
         "promessa_para": {"type": "string", "description": "AAAA-MM-DD, só se prometeu pagar."},
         "nota": {"type": "string"},
     }, ["contrato_id"])},
    {"name": "registrar_bloqueio", "description": "REGISTRA que o aparelho do contrato foi bloqueado (só o registro; o bloqueio do celular é feito pela equipe). A pessoa autoriza no pedido de permissão do Claude Desktop.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}, "observacao": {"type": "string", "description": "Como foi bloqueado, ex.: iCloud."}}, ["contrato_id"])},
    {"name": "registrar_desbloqueio", "description": "REGISTRA que o aparelho do contrato foi liberado. A pessoa autoriza no pedido de permissão do Claude Desktop.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}}, ["contrato_id"])},
    {"name": "ajustar_parcela", "description": "SOMA ou TIRA valor de uma parcela em aberto, ou muda o valor/data dela. acrescimo é o ajuste TOTAL da parcela: positivo = valor a mais (ex.: 5.00 soma R$ 5,00 à parcela), negativo = desconto (ex.: -20.00), 0 = remove o ajuste. valor_base muda o valor da própria parcela. Tudo que for omitido continua como está (consulte o contrato antes: o campo ajuste mostra o que já existe). O Pix aberto é refeito com o valor novo. Para juros de atraso, use perdoar_juros ou registre_pagamento com juros_pago.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"},
         "parcela_numero": {"type": "integer", "description": "Se omitido, usa a primeira em aberto."},
         "acrescimo": {"type": "string", "description": "Ajuste total da parcela, com sinal: 5.00 soma, -20.00 desconta, 0 remove."},
         "valor_base": {"type": "string", "description": "Novo valor da parcela sem o ajuste, ex.: 160.00."},
         "data_vencimento": {"type": "string", "description": "AAAA-MM-DD, nova data de cobrança."},
         "motivo": {"type": "string", "description": "Por que o ajuste (até 120 letras), ex.: troca de tela."},
     }, ["contrato_id"])},
    {"name": "perdoar_juros", "description": "PERDOA juros de atraso de uma parcela (acordo). Sem o campo juros, perdoa todos os de hoje. A pessoa autoriza no pedido de permissão do Claude Desktop.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"}, "parcela_numero": {"type": "integer"},
         "juros": {"type": "string", "description": "Quanto perdoar, ex.: 10.00. Omitido = todos os juros de hoje."},
         "nota": {"type": "string"},
     }, ["contrato_id"])},
    {"name": "adiar_parcela", "description": "ADIA a cobrança de uma parcela para uma nova data (acordo). Os juros recomeçam a contar da nova data.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"}, "parcela_numero": {"type": "integer"},
         "nova_data": {"type": "string", "description": "AAAA-MM-DD, depois da cobrança atual e não no passado."},
         "nota": {"type": "string"},
     }, ["contrato_id", "nova_data"])},
    {"name": "desfazer_acordo", "description": "DESFAZ um acordo (perdão de juros ou adiamento) enquanto a parcela não recebeu pagamento. O id do acordo vem de consultar_contrato.",
     "input_schema": _esquema({"acordo_id": {"type": "integer"}}, ["acordo_id"])},
    {"name": "estornar_pagamento", "description": "ESTORNA (desfaz) um pagamento registrado: a parcela volta a ficar em aberto. O id do pagamento vem de consultar_contrato. Use quando o pagamento foi lançado errado.",
     "input_schema": _esquema({"pagamento_id": {"type": "integer"}}, ["pagamento_id"])},
    {"name": "corrigir_pagamento", "description": "CORRIGE data, juros, forma ou observação de um pagamento já registrado (o valor da parcela paga não muda; para isso, estorne e registre de novo). O id do pagamento vem de consultar_contrato. Campos omitidos continuam como estão.",
     "input_schema": _esquema({
         "pagamento_id": {"type": "integer"},
         "data_pagamento": {"type": "string", "description": "AAAA-MM-DD, não pode ser futura."},
         "juros_pago": {"type": "string"},
         "forma": {"type": "string", "enum": ["pix", "dinheiro", "outro"]},
         "observacao": {"type": "string"},
     }, ["pagamento_id"])},
    {"name": "listar_estoque", "description": "Lista os aparelhos do estoque ainda sem contrato (id, modelo, IMEI). Necessário para criar um contrato. Só leitura.",
     "input_schema": _esquema({}, [])},
    {"name": "relatorio_periodo", "description": "Relatório financeiro de um período: previsto, recebido (de parcelas do período, atrasadas e adiantadas), juros, por forma de pagamento, contratos em atraso, novos clientes e quitados. Sem datas, usa do dia 1 do mês até hoje. Use para 'quanto entrou hoje/esta semana/este mês'. Só leitura.",
     "input_schema": _esquema({"inicio": {"type": "string", "description": "AAAA-MM-DD"}, "fim": {"type": "string", "description": "AAAA-MM-DD"}}, [])},
    {"name": "listar_pagamentos", "description": "Histórico de pagamentos (até 40), de um contrato e/ou de um período, com o id de cada um. Sem filtros, mostra os últimos 7 dias. Só leitura.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}, "inicio": {"type": "string", "description": "AAAA-MM-DD"}, "fim": {"type": "string", "description": "AAAA-MM-DD"}}, [])},
    {"name": "pendencias_pix", "description": "O que está pendente no painel Pix: entradas do extrato da Cora sem pagamento registrado (com clientes prováveis), Pix pagos em duplicidade, comprovantes aguardando conferência e Pix com erro. Mostra também se a cobrança automática está pausada. Só leitura.",
     "input_schema": _esquema({}, [])},
    {"name": "saude_das_rotinas", "description": "Mostra se as rotinas agendadas (cobrança, extrato, parcelas…) rodaram e se alguma falhou, atrasou ou travou. Só leitura.",
     "input_schema": _esquema({}, [])},
    {"name": "cadastrar_cliente", "description": "CADASTRA um cliente novo (nome, CPF, WhatsApp). Antes use buscar_cliente para não duplicar. Para importar uma lista, chame uma vez por cliente.",
     "input_schema": _esquema({"nome": {"type": "string"}, "cpf": {"type": "string", "description": "11 dígitos, com ou sem pontuação."},
                               "telefone": {"type": "string", "description": "WhatsApp com DDD, ex.: 88999990000."}, "endereco": {"type": "string"}}, ["nome", "cpf", "telefone"])},
    {"name": "editar_cliente", "description": "CORRIGE dados de um cliente (nome, CPF, telefone, endereço). O que for omitido continua como está.",
     "input_schema": _esquema({"cliente_id": {"type": "integer"}, "nome": {"type": "string"}, "cpf": {"type": "string"},
                               "telefone": {"type": "string"}, "endereco": {"type": "string"}}, ["cliente_id"])},
    {"name": "arquivar_cliente", "description": "ARQUIVA um cliente (some da lista principal, o histórico fica) ou o reativa (ativo=true). Não apaga nada.",
     "input_schema": _esquema({"cliente_id": {"type": "integer"}, "ativo": {"type": "boolean", "description": "false (padrão) arquiva; true reativa."}}, ["cliente_id"])},
    {"name": "cadastrar_contrato", "description": "CRIA um contrato novo a partir de um aparelho do ESTOQUE (use listar_estoque) e gera as parcelas. A parcela sai de valor_total ÷ num_parcelas (múltiplos de R$ 0,10). Confira os números com a pessoa antes. Não existe frequência 'dezenal'. Para cobrança semanal informe dia_semana (0=segunda … 6=domingo); mensal, dia_mes; quinzenal, dia_semana ou dia_mes + dia_mes_2 (quinzena=dias_mes); ou primeira_cobranca direto.",
     "input_schema": _esquema({
         "cliente_id": {"type": "integer"}, "aparelho_id": {"type": "integer", "description": "Do listar_estoque."},
         "apelido": {"type": "string", "description": "Ex.: iPhone 11."}, "valor_total": {"type": "string", "description": "Ex.: 2400.00"},
         "num_parcelas": {"type": "integer"}, "estrutura": {"type": "string", "enum": ["diaria", "semanal", "quinzenal", "mensal"]},
         "data_inicio": {"type": "string", "description": "AAAA-MM-DD, data da compra; padrão hoje."},
         "primeira_cobranca": {"type": "string", "description": "AAAA-MM-DD; se omitido, sai do dia de cobrança."},
         "dia_semana": {"type": "integer"}, "dia_mes": {"type": "integer"}, "dia_mes_2": {"type": "integer"},
         "quinzena": {"type": "string", "enum": ["semana", "dias_mes"]},
         "juros_diario": {"type": "string", "description": "Padrão 5.00 por dia de atraso."},
         "entrada": {"type": "string", "description": "Entrada recebida à vista (opcional)."}, "entrada_forma": {"type": "string", "enum": ["pix", "dinheiro", "outro"]},
         "parcelas_ja_pagas": {"type": "integer", "description": "Para contrato que já andava antes do sistema."}, "observacoes": {"type": "string"},
     }, ["cliente_id", "aparelho_id", "apelido", "valor_total", "num_parcelas", "estrutura"])},
    {"name": "editar_contrato", "description": "EDITA um contrato (apelido, juros_diario, valor_total, valor_parcela, num_parcelas, estrutura, data_inicio, primeira_cobranca, observacoes). O que for omitido continua. As parcelas em aberto são atualizadas e o Pix refeito. Para somar/tirar valor de UMA parcela use ajustar_parcela.",
     "input_schema": _esquema({
         "contrato_id": {"type": "integer"}, "apelido": {"type": "string"}, "juros_diario": {"type": "string"}, "valor_total": {"type": "string"},
         "valor_parcela": {"type": "string"}, "num_parcelas": {"type": "integer"}, "estrutura": {"type": "string", "enum": ["diaria", "semanal", "quinzenal", "mensal"]},
         "data_inicio": {"type": "string"}, "primeira_cobranca": {"type": "string"}, "observacoes": {"type": "string"},
     }, ["contrato_id"])},
    {"name": "quitar_contrato", "description": "MARCA o contrato como QUITADO: a cobrança dele para. Não cria pagamento nem apaga parcelas. Faça só quando a equipe confirmar.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}}, ["contrato_id"])},
    {"name": "cobranca_automatica", "description": "PAUSA ou RETOMA as cobranças automáticas (mensagem e Pix) de TODO o sistema. O primeiro começo do sistema só se faz pela tela.",
     "input_schema": _esquema({"acao": {"type": "string", "enum": ["pausar", "retomar"]}}, ["acao"])},
    {"name": "controlar_pix_parcela", "description": "Controla o Pix/cobrança de UMA parcela: suspender (cancela o Pix e a rotina para de cobrá-la), cancelar_pix, retomar (volta a cobrar; Pix novo na próxima rotina) ou gerar_pix. Nunca cancela Pix já pago.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}, "parcela_numero": {"type": "integer", "description": "Se omitido, a primeira em aberto."},
                               "acao": {"type": "string", "enum": ["suspender", "cancelar_pix", "retomar", "gerar_pix"]}}, ["contrato_id", "acao"])},
    {"name": "resolver_duplicidade_pix", "description": "MARCA como resolvida uma duplicidade de Pix (o valor já foi devolvido ao cliente). O id vem de pendencias_pix. Só registra no sistema.",
     "input_schema": _esquema({"cobranca_id": {"type": "integer"}}, ["cobranca_id"])},
    {"name": "conferir_comprovante", "description": "CONSULTA a Cora sobre um comprovante que o cliente mandou por WhatsApp; se o Pix caiu, dá a baixa e avisa o cliente. O id vem de pendencias_pix.",
     "input_schema": _esquema({"comprovante_id": {"type": "integer"}}, ["comprovante_id"])},
    {"name": "descartar_comprovante", "description": "DESCARTA o aviso de um arquivo que não era comprovante (foto qualquer). O id vem de pendencias_pix.",
     "input_schema": _esquema({"comprovante_id": {"type": "integer"}}, ["comprovante_id"])},
    {"name": "ignorar_entrada_extrato", "description": "IGNORA uma entrada do extrato da Cora que não é pagamento de parcela. O id (recebimento_id) vem de pendencias_pix.",
     "input_schema": _esquema({"recebimento_id": {"type": "integer"}}, ["recebimento_id"])},
    {"name": "vincular_entrada_extrato", "description": "LIGA uma entrada do extrato da Cora a um pagamento já registrado (registre antes com registrar_pagamento, forma pix). Os ids vêm de pendencias_pix e listar_pagamentos.",
     "input_schema": _esquema({"recebimento_id": {"type": "integer"}, "pagamento_id": {"type": "integer"}}, ["recebimento_id", "pagamento_id"])},
    {"name": "enviar_cobranca_whatsapp", "description": "ENVIA AGORA, no WhatsApp do cliente, a cobrança de hoje do contrato (mesma mensagem e Pix da rotina automática). Só envia se o contrato estiver atrasado ou vencendo hoje. Envia mensagem de verdade ao cliente.",
     "input_schema": _esquema({"contrato_id": {"type": "integer"}}, ["contrato_id"])},
]


# ── interface usada pela API (conector do Claude Desktop) ─────────────────────

RESUMO_DESCRICAO = (
    "Frase curta, em português, dizendo exatamente o que será gravado (cliente, parcela, valor, data). "
    "Ela aparece no pedido de permissão para a pessoa conferir antes de autorizar."
)


def catalogo() -> list[dict]:
    """As ferramentas como o conector as publica: nome, descrição, esquema e se gravam algo."""
    import copy

    itens = []
    for f in FERRAMENTAS:
        grava = f["name"] in ESCRITA
        esquema = copy.deepcopy(f["input_schema"])
        if grava:
            esquema["properties"]["resumo"] = {"type": "string", "description": RESUMO_DESCRICAO}
            esquema["required"] = list(esquema["required"]) + ["resumo"]
        itens.append({"name": f["name"], "description": f["description"], "input_schema": esquema, "grava": grava})
    return itens


def executar_ferramenta(nome: str, parametros: dict, usuario) -> tuple[str, str, bool, dict]:
    """Roda uma ferramenta. Devolve (texto para o Claude, resumo do que foi feito, se gravou algo, referências do
    que foi gravado, usadas para desfazer, ex.: ``{"pagamento_id": 7}``).

    Levanta ``ErroFerramenta`` quando o pedido não pode ser atendido (a mensagem é para a pessoa)."""
    import json

    parametros = dict(parametros or {})
    resumo_informado = str(parametros.pop("resumo", "") or "")[:300]
    if nome in LEITURA:
        try:
            return json.dumps(LEITURA[nome](**parametros), ensure_ascii=False), "", False, {}
        except TypeError as exc:
            raise ErroFerramenta(f"Parâmetros inválidos para {nome}: {exc}")
    if nome in ESCRITA:
        if not resumo_informado.strip():
            raise ErroFerramenta("Informe o resumo do que será gravado (campo resumo).")
        validar, executar = ESCRITA[nome]
        normalizados, resumo, avisos = validar(parametros)
        resultado = executar(normalizados, usuario)
        resultado, referencias = resultado if isinstance(resultado, tuple) else (resultado, {})
        texto = f"{resumo} -> {resultado}" + (" Avisos: " + " ".join(avisos) if avisos else "")
        return texto, resumo, True, referencias
    raise ErroFerramenta(f"Ferramenta desconhecida: {nome}")
