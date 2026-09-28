"""Paginação de listas já montadas em memória (telas que não são ``ListView``)."""

from django.core.paginator import Paginator


def paginar(request, itens, por_pagina):
    """Devolve ``page_obj``/``is_paginated`` para o ``_pagination.html``.

    Página inválida (fora do intervalo ou não numérica) cai na mais próxima em
    vez de dar erro — a lista muda ao longo do dia e o link pode ter ficado
    velho.
    """
    paginador = Paginator(itens, por_pagina)
    pagina = paginador.get_page(request.GET.get("page"))
    return {
        "page_obj": pagina,
        "paginator": paginador,
        "is_paginated": paginador.num_pages > 1,
    }
