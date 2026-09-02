from django.contrib.auth.mixins import AccessMixin


class DonoRequeridoMixin(AccessMixin):
    """Restringe a view ao perfil ``dono`` (e a superusuários).

    Modelo de acesso (Alisson, 02/09): o ``dono`` enxerga tudo que o
    ``financeiro`` enxerga e ainda tem telas e ações a mais (relatórios,
    acordos, configurações). O inverso não vale.

    Telas compartilhadas continuam só com ``LoginRequiredMixin``; use este
    mixin apenas nas telas exclusivas do dono. Anônimo é mandado para o login;
    ``financeiro`` autenticado recebe 403.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not getattr(request.user, "is_dono", False):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
