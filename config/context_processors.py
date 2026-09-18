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
    "relatorios:inicio": "favicon-relatorios-inicio.svg",
    "relatorios:painel": "favicon-relatorios-painel.svg",
    "usuarios:login": "favicon-usuarios-login.svg",
}


def favicon(request):
    resolver_match = getattr(request, "resolver_match", None)
    view_name = getattr(resolver_match, "view_name", None)
    return {"favicon_arquivo": FAVICON_POR_PAGINA.get(view_name, "favicon.svg")}
