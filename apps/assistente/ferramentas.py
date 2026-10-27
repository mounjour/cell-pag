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
    "ajustar_parcela": (validar_ajuste, executar_ajuste),
    "perdoar_juros": (validar_perdao, executar_perdao),
    "adiar_parcela": (validar_adiamento, executar_adiamento),
    "desfazer_acordo": (validar_desfazer_acordo, executar_desfazer_acordo),
    "estornar_pagamento": (validar_estorno, executar_estorno),
    "corrigir_pagamento": (validar_edicao_pagamento, executar_edicao_pagamento),
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
