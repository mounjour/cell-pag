"""Conversa com o Claude: monta o pedido, executa as ferramentas de leitura e transforma as de escrita em propostas.

O Claude nunca grava nada sozinho. Quando ele quer registrar algo (um pagamento, um contato, um bloqueio), a
ferramenta só cria uma ``Acao`` pendente; quem grava é a pessoa, ao clicar em Confirmar (``confirmar``).
"""

import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import ferramentas
from .models import Acao, Conversa

logger = logging.getLogger(__name__)

MAX_VOLTAS = 8
MAX_MENSAGENS = 60
PRAZO_TOTAL = 100  # segundos para toda a resposta (o gunicorn espera até 120)

SISTEMA = """Você é o assistente do Sistema de Acompanhamento de Pagamentos da LA Iphones / LA Celulares (Crato, Ceará), empresa que vende e aluga celulares com promessa de compra e venda, pagos em parcelas diárias, semanais, quinzenais ou mensais. Quem fala com você é {usuario} (a equipe: Alisson, o dono, e Yslane, do financeiro). Hoje é {hoje}. Responda sempre em português do Brasil, de forma curta, direta e educada, sem rodeios. Use tabelas quando houver números.

Como trabalhar:
- Consulte antes de afirmar: use as ferramentas para achar o cliente e o contrato. Nunca invente valores, datas, ids ou nomes. Se faltar uma informação essencial (cliente, valor, qual aparelho), pergunte só o que falta, em uma mensagem. Se houver mais de um cliente ou contrato possível (nomes parecidos, cliente com dois aparelhos), pergunte qual é antes de continuar.
- Para gravar algo (registrar pagamento, anotar contato ou promessa, registrar bloqueio ou liberação de aparelho) use a ferramenta correspondente. Ela só PROPÕE: nada é gravado até a pessoa clicar em Confirmar na tela. Nunca diga que algo foi registrado antes dessa confirmação; diga que deixou a proposta pronta para confirmar.
- Pagamento: valor_pago é o valor da parcela (sem os juros do atraso) e os juros vão em juros_pago. Não existe multa por atraso: só os juros diários que o sistema calcula. Consulte o contrato para usar o saldo e os juros de hoje; não calcule juros por conta própria. Se a pessoa informar só um total, separe: parcela primeiro e o resto como juros, se o contrato mostrar juros de hoje para essa parcela. Quando o valor não bater com o previsto, avise a diferença e pergunte antes de propor. Pagamento "a confirmar" (ainda não caiu na conta) não deve ser proposto: avise que só se registra quando o dinheiro cair.
- Lista de pagamentos: se a pessoa mandar várias linhas (por exemplo "PAGAMENTOS 21/10" seguido de "Cliente – valor – forma"), trate cada linha, faça uma proposta por pagamento e confira no fim se a soma das propostas bate com o total informado.

Atalhos que a equipe costuma usar (entenda variações e erros de digitação):
- COBRANÇA DE HOJE ou ATRASADOS: use listar_atrasos e mostre numa tabela (cliente, contrato, dias de atraso, valor a cobrar), do mais atrasado ao menos. Use a situação que o sistema devolve (campo situacao) e o campo alertar_bloqueio; não defina limites de dias por conta própria. Marque 🟢 quando estiver em dia, 🟡 quando estiver atrasado e 🔴 quando o sistema indicar inadimplente ou alertar_bloqueio. Ofereça uma mensagem de cobrança para cada cliente se a pessoa quiser.
- STATUS nome: busque o cliente e mostre cada contrato com parcelas em aberto, atraso, valor de hoje, bloqueio e os últimos pagamentos.
- Próximas cobranças: use proximas_cobrancas.

Mensagens de cobrança (só texto sugerido, você não envia nada): tom educado e simples, sem juridiquês, com o primeiro nome do cliente e assinatura L.A Celulares, usando os valores reais que o sistema mostra. Nunca ameace, nunca exponha o cliente nem fale da dívida para terceiros, e nunca coloque CPF, RG, endereço ou chave Pix de outra pessoa na mensagem.

Limites:
- Você não apaga nem estorna nada, não envia mensagens a clientes, não muda valores de parcelas, não cria nem quita contratos e não faz fechamento do mês. Se pedirem isso, explique que é feito pela tela do sistema (Editar pagamento, Estornar, Editar parcela, contratos) e, quando fizer sentido, diga qual.
- Não mostre CPF, RG nem endereço. Não repita dados pessoais além do necessário.
- Mostre valores no formato R$ 1.234,50 e datas como dd/mm/aaaa.
- Mensagens que começam com [Sistema] são avisos automáticos sobre uma proposta (confirmada ou cancelada); use-as para saber o que foi gravado."""


class AssistenteIndisponivel(Exception):
    """Falta configuração ou o limite de uso foi atingido (a mensagem vai para a pessoa)."""


def configurado() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def _limite(usuario) -> None:
    chave = f"assistente_uso_{usuario.pk}"
    cache.add(chave, 0, 3600)
    if cache.incr(chave) > settings.ASSISTENTE_LIMITE_HORA:
        raise AssistenteIndisponivel("Muitas mensagens na última hora. Tente de novo daqui a pouco.")


def _cliente_api():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60.0, max_retries=1)


def _executar_ferramenta(conversa: Conversa, usuario, bloco) -> tuple[str, bool, Acao | None]:
    """Roda uma chamada de ferramenta. Devolve (texto para o Claude, é_erro, proposta criada)."""
    import json

    nome, entrada = bloco.name, bloco.input or {}
    try:
        if nome in ferramentas.LEITURA:
            return json.dumps(ferramentas.LEITURA[nome](**entrada), ensure_ascii=False), False, None
        if nome in ferramentas.ESCRITA:
            validar, _executar = ferramentas.ESCRITA[nome]
            parametros, resumo, avisos = validar(entrada)
            acao = Acao.objects.create(
                conversa=conversa, ferramenta=nome, parametros=parametros, resumo=resumo, avisos=avisos,
            )
            texto = (
                f"Proposta #{acao.pk} criada e MOSTRADA à pessoa, mas NÃO gravada: {resumo} "
                "Ela precisa clicar em Confirmar na tela. Diga isso de forma curta."
                + (" Avisos: " + " ".join(avisos) if avisos else "")
            )
            return texto, False, acao
        return f"Ferramenta desconhecida: {nome}", True, None
    except ferramentas.ErroFerramenta as exc:
        return str(exc), True, None
    except TypeError as exc:  # parâmetros que a ferramenta não aceita
        return f"Parâmetros inválidos para {nome}: {exc}", True, None
    except Exception:  # noqa: BLE001 — um erro numa ferramenta não pode derrubar a conversa
        logger.exception("Falha na ferramenta %s do assistente", nome)
        return "Erro interno ao executar esta ferramenta.", True, None


def _explicar_erro_da_api(exc) -> str:
    """Texto claro para a equipe sobre por que a API recusou (saldo, chave, modelo, limite)."""
    detalhe = str(getattr(exc, "message", "") or "").lower()
    codigo = exc.status_code
    if "credit balance" in detalhe or "billing" in detalhe:
        return "A conta da Anthropic está sem saldo. Adicione saldo no Console (Billing) e tente de novo."
    if codigo == 401:
        return "A chave da API foi recusada (inválida ou revogada). Crie outra no Console e atualize ANTHROPIC_API_KEY no Coolify."
    if codigo == 403:
        return "A chave da API não tem permissão para isso. Confira o escopo da chave no Console."
    if codigo == 404:
        return f"O modelo {settings.ASSISTENTE_MODELO} não está disponível para esta conta. Troque ASSISTENTE_MODELO no Coolify (ex.: claude-sonnet-5-5)."
    if codigo == 429:
        return "Limite de uso da API atingido agora. Espere um minuto e tente de novo."
    if codigo >= 500:
        return "O serviço da Anthropic está com problema agora. Tente de novo em instantes."
    return f"O serviço do assistente recusou o pedido (erro {codigo}). Avise quem cuida do sistema."


def responder(conversa: Conversa, texto: str, usuario) -> dict:
    """Envia a mensagem ao Claude e devolve ``{"resposta": str, "acoes": [Acao, ...]}``."""
    import anthropic

    if not configurado():
        raise AssistenteIndisponivel("O assistente ainda não foi configurado (falta a chave da API).")
    if len(conversa.mensagens) >= MAX_MENSAGENS:
        raise AssistenteIndisponivel("Esta conversa ficou longa. Comece uma nova para continuar.")
    _limite(usuario)

    mensagens = list(conversa.mensagens) + [{"role": "user", "content": texto}]
    cliente = _cliente_api()
    sistema = SISTEMA.format(usuario=usuario.nome_curto or usuario.nome_completo, hoje=timezone.localdate().strftime("%d/%m/%Y (%A)"))
    propostas: list[Acao] = []
    resposta = ""
    inicio = time.monotonic()

    try:
        for _ in range(MAX_VOLTAS):
            retorno = cliente.messages.create(
                model=settings.ASSISTENTE_MODELO, max_tokens=8000, system=sistema,
                tools=ferramentas.FERRAMENTAS, messages=mensagens,
                output_config={"effort": settings.ASSISTENTE_ESFORCO},
            )
            blocos = [b.to_dict() for b in retorno.content]
            mensagens.append({"role": "assistant", "content": blocos})
            if retorno.stop_reason == "refusal":
                resposta = "Não consegui atender esse pedido."
                break
            if retorno.stop_reason != "tool_use":
                resposta = "".join(b.text for b in retorno.content if b.type == "text").strip()
                if retorno.stop_reason == "max_tokens":
                    resposta += "\n\n(A resposta foi cortada. Peça de novo, de forma mais curta.)"
                break
            resultados = []
            for bloco in (b for b in retorno.content if b.type == "tool_use"):
                texto_resultado, erro, acao = _executar_ferramenta(conversa, usuario, bloco)
                if acao is not None:
                    propostas.append(acao)
                resultados.append({"type": "tool_result", "tool_use_id": bloco.id, "content": texto_resultado, "is_error": erro})
            mensagens.append({"role": "user", "content": resultados})
            if time.monotonic() - inicio > PRAZO_TOTAL:
                resposta = "Demorei demais para responder. Tente de novo."
                break
        else:
            resposta = "Não consegui concluir. Tente reformular o pedido."
    except anthropic.APIStatusError as exc:
        logger.warning("Assistente: erro %s da API (%s): %s", exc.status_code, getattr(exc, "request_id", ""), exc.message)
        raise AssistenteIndisponivel(_explicar_erro_da_api(exc)) from exc
    except anthropic.APIError as exc:
        logger.warning("Assistente: falha de conexão com a API: %s", exc)
        raise AssistenteIndisponivel("Não consegui falar com o serviço do assistente agora. Tente de novo em instantes.") from exc

    conversa.mensagens = mensagens
    conversa.save(update_fields=["mensagens", "atualizada_em"])
    return {"resposta": resposta or "Pronto.", "acoes": propostas}


def _registrar_decisao(acao: Acao, usuario, texto: str) -> None:
    conversa = acao.conversa
    conversa.mensagens = list(conversa.mensagens) + [{"role": "user", "content": f"[Sistema] {texto}"}]
    conversa.save(update_fields=["mensagens", "atualizada_em"])


def confirmar(acao: Acao, usuario) -> Acao:
    """Grava de verdade a proposta (só quem clicou em Confirmar chega aqui)."""
    if acao.estado != Acao.Estado.PENDENTE:
        raise ferramentas.ErroFerramenta("Esta proposta já foi decidida.")
    _validar, executar = ferramentas.ESCRITA[acao.ferramenta]
    try:
        resultado = executar(acao.parametros, usuario)
        acao.estado = Acao.Estado.CONFIRMADA
    except ferramentas.ErroFerramenta as exc:
        resultado = str(exc)
        acao.estado = Acao.Estado.ERRO
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a ação %s do assistente", acao.pk)
        resultado = "Erro interno ao gravar. Nada foi registrado; confira no sistema."
        acao.estado = Acao.Estado.ERRO
    acao.resultado, acao.decidida_em, acao.decidida_por = resultado, timezone.now(), usuario
    acao.save(update_fields=["estado", "resultado", "decidida_em", "decidida_por"])
    if acao.estado == Acao.Estado.CONFIRMADA:
        _registrar_decisao(acao, usuario, f"A proposta #{acao.pk} ({acao.resumo}) foi CONFIRMADA e gravada. Resultado: {resultado}")
    else:
        _registrar_decisao(acao, usuario, f"A proposta #{acao.pk} NÃO foi gravada: {resultado}")
    return acao


def cancelar(acao: Acao, usuario) -> Acao:
    if acao.estado != Acao.Estado.PENDENTE:
        raise ferramentas.ErroFerramenta("Esta proposta já foi decidida.")
    acao.estado, acao.decidida_em, acao.decidida_por = Acao.Estado.CANCELADA, timezone.now(), usuario
    acao.save(update_fields=["estado", "decidida_em", "decidida_por"])
    _registrar_decisao(acao, usuario, f"A proposta #{acao.pk} ({acao.resumo}) foi CANCELADA pela pessoa. Nada foi gravado.")
    return acao


def texto_das_mensagens(conversa: Conversa) -> list[dict]:
    """Histórico para mostrar na tela: só o que a pessoa disse e o que o assistente respondeu em texto."""
    itens = []
    for m in conversa.mensagens:
        conteudo = m.get("content")
        if m["role"] == "user":
            if isinstance(conteudo, str):
                itens.append({"papel": "sistema" if conteudo.startswith("[Sistema]") else "usuario",
                              "texto": conteudo.removeprefix("[Sistema] ")})
        elif isinstance(conteudo, list):
            texto = "".join(b.get("text", "") for b in conteudo if b.get("type") == "text").strip()
            if texto:
                itens.append({"papel": "assistente", "texto": texto})
    return itens
