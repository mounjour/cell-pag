from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .forms import CadastroPorConviteForm, LoginForm
from .mixins import DonoRequeridoMixin
from .models import ConviteUsuario, Usuario


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


class AjudaView(LoginRequiredMixin, TemplateView):
    """Ajuda do sistema: as explicações completas que não cabem nos balões de "Como funciona"."""

    template_name = "usuarios/ajuda.html"

    def get_context_data(self, **kwargs):
        from urllib.parse import quote

        ctx = super().get_context_data(**kwargs)
        numero = "".join(c for c in settings.SUPORTE_WHATSAPP if c.isdigit())
        texto = quote(f"Olá! Sou {self.request.user.nome_curto} e preciso de ajuda com o CellPage.")
        ctx["suporte_whatsapp_url"] = f"https://wa.me/{numero}?text={texto}" if numero else ""
        return ctx


# ── Cadastro rápido por código de convite ─────────────────────────────────────
TENTATIVAS_CODIGO_MAX = 10
TENTATIVAS_CODIGO_JANELA = 15 * 60  # segundos


def _chave_tentativas(request) -> str:
    from axes.helpers import get_client_ip_address

    return f"convite_tentativas:{get_client_ip_address(request)}"


def _motivo_invalido(convite) -> str:
    if convite is None:
        return "Código inválido. Confira com quem enviou o convite e tente de novo."
    return {
        "usado": "Este código já foi usado. Peça um novo código a quem enviou o convite.",
        "expirado": "Este código expirou. Peça um novo código a quem enviou o convite.",
        "cancelado": "Este código foi cancelado. Peça um novo código a quem enviou o convite.",
    }.get(convite.situacao, "")


class CadastroConviteView(TemplateView):
    """Tela pública de cadastro. Só funciona com um código de convite válido:
    sem código (ou com código inválido, expirado ou já usado) ninguém cria usuário."""

    template_name = "usuarios/cadastro.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, "Você já está dentro do sistema. Saia da conta para usar um convite.")
            return redirect("relatorios:inicio")
        return super().dispatch(request, *args, **kwargs)

    def _falhou(self, request):
        chave = _chave_tentativas(request)
        cache.add(chave, 0, TENTATIVAS_CODIGO_JANELA)
        try:
            cache.incr(chave)
        except ValueError:
            cache.set(chave, 1, TENTATIVAS_CODIGO_JANELA)

    def _resolver(self, request, codigo_digitado):
        """Devolve (convite, erro). Conta a tentativa quando o código não presta."""
        codigo = ConviteUsuario.normalizar(codigo_digitado)
        if not codigo:
            return None, ""
        if cache.get(_chave_tentativas(request), 0) >= TENTATIVAS_CODIGO_MAX:
            return None, "Muitas tentativas com código errado. Aguarde alguns minutos e tente de novo."
        convite = ConviteUsuario.objects.filter(codigo=codigo).first()
        if convite is not None and convite.esta_valido:
            return convite, ""
        self._falhou(request)
        return None, _motivo_invalido(convite)

    def _render(self, request, convite, erro, form=None):
        if erro:
            messages.error(request, erro)
        ctx = self.get_context_data(convite=convite, erro=erro, form=form or CadastroPorConviteForm())
        return self.render_to_response(ctx)

    def get(self, request, codigo=None, *args, **kwargs):
        convite, erro = self._resolver(request, codigo or request.GET.get("codigo", ""))
        return self._render(request, convite, erro)

    def post(self, request, codigo=None, *args, **kwargs):
        convite, erro = self._resolver(request, request.POST.get("codigo", "") or codigo or "")
        if convite is None:
            return self._render(request, None, erro)
        if "senha" not in request.POST:  # só digitou o código (passo 1)
            return self._render(request, convite, "")
        form = CadastroPorConviteForm(request.POST)
        if not form.is_valid():
            return self._render(request, convite, "", form)
        dados = form.cleaned_data
        with transaction.atomic():
            atual = ConviteUsuario.objects.select_for_update().get(pk=convite.pk)
            if not atual.esta_valido:  # alguém usou no meio tempo
                self._falhou(request)
                return self._render(request, None, _motivo_invalido(atual))
            usuario = Usuario(
                username=dados["email"], first_name=dados["nome"], email=dados["email"],
                perfil=atual.perfil, termos_aceitos_versao=settings.TERMOS_VERSAO,
                termos_aceitos_em=timezone.now(),
            )
            usuario.set_password(dados["senha"])
            usuario.save()
            atual.usado_em = timezone.now()
            atual.usado_por = usuario
            atual.save(update_fields=["usado_em", "usado_por"])
        login(request, usuario, backend="apps.usuarios.backends.UsuarioOuEmailBackend")
        messages.success(request, f"Usuário criado. Bem-vindo(a), {usuario.nome_curto}!")
        return redirect("relatorios:inicio")


class ConvitesView(DonoRequeridoMixin, TemplateView):
    """Tela do dono: gera códigos de convite e acompanha os que já criou."""

    template_name = "usuarios/convites.html"

    def get_context_data(self, **kwargs):
        from urllib.parse import quote

        ctx = super().get_context_data(**kwargs)
        convites = list(ConviteUsuario.objects.select_related("criado_por", "usado_por")[:30])
        novo_id = self.request.session.pop("convite_novo_id", None)
        for c in convites:
            c.link = self.request.build_absolute_uri(reverse("usuarios:cadastro_codigo", args=[c.codigo]))
            c.whatsapp = "https://wa.me/?text=" + quote(
                f"Olá! Aqui está o seu convite para criar o seu usuário no CellPage: {c.link}\n"
                f"Código: {c.codigo_formatado} (vale uma vez só e expira em breve)."
            )
            c.novo = c.pk == novo_id
        ctx["convites"] = convites
        ctx["perfis"] = Usuario.Perfil.choices
        ctx["validade_horas"] = ConviteUsuario.VALIDADE_HORAS
        return ctx

    def post(self, request, *args, **kwargs):
        perfil = request.POST.get("perfil", Usuario.Perfil.FINANCEIRO)
        if perfil not in Usuario.Perfil.values:
            perfil = Usuario.Perfil.FINANCEIRO
        convite = ConviteUsuario.gerar(request.user, perfil)
        request.session["convite_novo_id"] = convite.pk
        messages.success(request, f"Código {convite.codigo_formatado} gerado. Copie e envie para a pessoa.")
        return redirect("usuarios:convites")


@login_required
@require_POST
def convite_cancelar(request, pk):
    if not request.user.is_dono:
        return HttpResponse(status=403)
    convite = ConviteUsuario.objects.filter(pk=pk, usado_em__isnull=True, revogado_em__isnull=True).first()
    if convite is not None:
        convite.revogado_em = timezone.now()
        convite.save(update_fields=["revogado_em"])
        messages.success(request, f"Código {convite.codigo_formatado} cancelado.")
    return redirect("usuarios:convites")
