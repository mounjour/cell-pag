"""Context processors do projeto (registrados em config/settings.py)."""

# Um favicon por pagina (nao so por app) — ver templates/base.html.
# Chave: request.resolver_match.view_name ("app:nome_da_url").
# Rotas sem entrada aqui (downloads, webhooks, acoes) caem no "favicon.svg" generico.
FAVICON_POR_PAGINA = {
    "clientes:lista": "favicon-clientes-lista.svg",
    "clientes:detalhe": "favicon-clientes-detalhe.svg",
    "clientes:novo": "favicon-clientes-novo.svg",
    "clientes:editar": "favicon-clientes-editar.svg",
    "contratos:lista": "favicon-contratos-lista.svg",
    "contratos:detalhe": "favicon-contratos-detalhe.svg",
    "contratos:novo": "favicon-contratos-novo.svg",
    "contratos:editar": "favicon-contratos-editar.svg",
    "pagamentos:cobrar_hoje": "favicon-pagamentos-cobrar-hoje.svg",
    "pagamentos:pix_painel": "favicon-pagamentos-pix.svg",
    "pagamentos:historico": "favicon-pagamentos-historico.svg",
    "pagamentos:conexoes": "favicon-pagamentos-conexoes.svg",
    "relatorios:inicio": "favicon-relatorios-inicio.svg",
    "relatorios:painel": "favicon-relatorios-painel.svg",
    "usuarios:login": "favicon-usuarios-login.svg",
}


def shell(request):
    """Dados do menu. O contador de "Cobrar hoje" é preguiçoso: só é calculado
    (e vem do cache) se o template realmente o usar."""
    if not request.user.is_authenticated:
        return {}
    from django.utils.functional import SimpleLazyObject

    from apps.pagamentos.badge import (
        contagem_a_bloquear, contagem_a_desbloquear, contagem_cobrar_hoje, contagem_promessas,
    )

    def pix_alertas():
        from apps.pagamentos.models import CobrancaCora, ComprovanteRecebido

        duplicadas = CobrancaCora.objects.filter(
            duplicada=True, duplicidade_resolvida_em__isnull=True
        ).count()
        comprovantes = ComprovanteRecebido.objects.filter(
            status=ComprovanteRecebido.Status.AGUARDANDO
        ).count()
        return duplicadas + comprovantes

    def whatsapp_desconectado():
        from apps.pagamentos.badge import status_whatsapp

        return status_whatsapp() not in ("open", "simulado")

    def cobrancas_pausadas():
        from apps.pagamentos.models import ConfiguracaoCobranca

        return ConfiguracaoCobranca.esta_pausada()

    def aparelhos_a_bloquear():
        return contagem_a_bloquear()

    def aparelhos_a_bloquear_rotulo():
        return "aparelho para bloquear" if contagem_a_bloquear() == 1 else "aparelhos para bloquear"

    def promessas_a_retornar():
        return contagem_promessas()

    def promessas_a_retornar_rotulo():
        return "promessa de pagamento" if contagem_promessas() == 1 else "promessas de pagamento"

    def aparelhos_a_desbloquear():
        return contagem_a_desbloquear()

    def aparelhos_a_desbloquear_rotulo():
        return "aparelho para desbloquear" if contagem_a_desbloquear() == 1 else "aparelhos para desbloquear"

    def aparelhos_bloqueio_pendente():
        return contagem_a_bloquear() + contagem_a_desbloquear()

    def importacoes_pendentes():
        from apps.contratos.models import ImportacaoContratoPendente
        return ImportacaoContratoPendente.objects.filter(resolvida_em__isnull=True).count()

    def notificacoes_n():
        return (
            pix_alertas()
            + importacoes_pendentes()
            + (1 if whatsapp_desconectado() else 0)
            + (1 if cobrancas_pausadas() else 0)
            + (1 if aparelhos_a_bloquear() else 0)
            + (1 if aparelhos_a_desbloquear() else 0)
            + (1 if promessas_a_retornar() else 0)
        )

    def rotulo_importacoes_pendentes():
        quantidade = importacoes_pendentes()
        return "pendência" if quantidade == 1 else "pendências"

    return {
        "cobrar_hoje_n": SimpleLazyObject(contagem_cobrar_hoje),
        "pix_alertas_n": SimpleLazyObject(pix_alertas),  # duplicidades + comprovantes a conferir
        "whatsapp_desconectado": SimpleLazyObject(whatsapp_desconectado),
        "cobrancas_pausadas": SimpleLazyObject(cobrancas_pausadas),
        "aparelhos_a_bloquear_n": SimpleLazyObject(aparelhos_a_bloquear),
        "aparelhos_a_bloquear_rotulo": SimpleLazyObject(aparelhos_a_bloquear_rotulo),
        "promessas_a_retornar_n": SimpleLazyObject(promessas_a_retornar),
        "promessas_a_retornar_rotulo": SimpleLazyObject(promessas_a_retornar_rotulo),
        "aparelhos_a_desbloquear_n": SimpleLazyObject(aparelhos_a_desbloquear),
        "aparelhos_a_desbloquear_rotulo": SimpleLazyObject(aparelhos_a_desbloquear_rotulo),
        "bloqueios_pendentes_n": SimpleLazyObject(aparelhos_bloqueio_pendente),
        "importacoes_pendentes_n": SimpleLazyObject(importacoes_pendentes),
        "notificacoes_n": SimpleLazyObject(notificacoes_n),
        "importacoes_pendentes_rotulo": SimpleLazyObject(rotulo_importacoes_pendentes),
    }


def favicon(request):
    resolver_match = getattr(request, "resolver_match", None)
    view_name = getattr(resolver_match, "view_name", None)
    return {"favicon_arquivo": FAVICON_POR_PAGINA.get(view_name, "favicon.svg")}
