from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


class TermosAceitosMiddleware:
    """Manda para a tela de aceite quem ainda não aceitou a versão atual dos termos.

    Só vale para quem está logado. Ficam livres: a própria tela de termos, o
    aceite, o logout e os arquivos estáticos — senão a pessoa não conseguiria
    nem ler os termos, nem aceitar, nem sair.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._precisa_aceitar(request):
            destino = reverse("usuarios:termos")
            if request.method == "GET":
                destino += "?" + urlencode({"next": request.get_full_path()})
            return redirect(destino)
        return self.get_response(request)

    def _precisa_aceitar(self, request) -> bool:
        if not settings.TERMOS_EXIGIR_ACEITE:
            return False
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return False
        if usuario.termos_aceitos_versao == settings.TERMOS_VERSAO:
            return False
        livres = (
            reverse("usuarios:termos"),
            reverse("usuarios:termos_aceitar"),
            reverse("usuarios:logout"),
            settings.STATIC_URL if settings.STATIC_URL.startswith("/") else "/" + settings.STATIC_URL,
        )
        return not request.path.startswith(livres)
