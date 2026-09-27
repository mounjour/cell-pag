from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST

from .forms import LoginForm


class LoginView(auth_views.LoginView):
    """Login com "Manter conectado": marcado, a sessão dura
    ``SESSION_MANTER_CONECTADO_DIAS`` dias; desmarcado, vale o padrão
    (``SESSION_COOKIE_AGE``, 12 h de inatividade)."""

    template_name = "usuarios/login.html"
    authentication_form = LoginForm

    def form_valid(self, form):
        resposta = super().form_valid(form)
        if form.cleaned_data.get("manter_conectado"):
            self.request.session.set_expiry(
                settings.SESSION_MANTER_CONECTADO_DIAS * 24 * 60 * 60
            )
        return resposta


@login_required
@require_POST
def salvar_tema(request):
    """Guarda o tema (claro/escuro) escolhido no botão sol/lua na conta do usuário."""
    tema = request.POST.get("tema")
    if tema not in request.user.Tema.values:
        return HttpResponseBadRequest("tema inválido")
    request.user.tema = tema
    request.user.save(update_fields=["tema"])
    return HttpResponse(status=204)
