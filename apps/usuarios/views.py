from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

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


def _destino_seguro(request, padrao="relatorios:inicio"):
    destino = request.POST.get("next") or request.GET.get("next") or ""
    permitido = url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return destino if destino and permitido else reverse_lazy(padrao)


class TermosView(TemplateView):
    """Termos de uso e privacidade. Qualquer pessoa lê; quem está logado e ainda
    não aceitou esta versão vê o botão de aceite."""

    template_name = "usuarios/termos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        usuario = self.request.user
        ctx["versao"] = settings.TERMOS_VERSAO
        ctx["precisa_aceitar"] = (
            usuario.is_authenticated and usuario.termos_aceitos_versao != settings.TERMOS_VERSAO
        )
        ctx["proximo"] = self.request.GET.get("next", "")
        return ctx


@login_required
@require_POST
def termos_aceitar(request):
    if request.POST.get("aceito") != "1":
        return redirect(f"{reverse_lazy('usuarios:termos')}?next={request.POST.get('next', '')}")
    usuario = request.user
    usuario.termos_aceitos_versao = settings.TERMOS_VERSAO
    usuario.termos_aceitos_em = timezone.now()
    usuario.save(update_fields=["termos_aceitos_versao", "termos_aceitos_em"])
    return redirect(_destino_seguro(request))
