from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("", views.ClienteListView.as_view(), name="lista"),
    path("novo/", views.ClienteCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.ClienteDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="editar"),
    path("<int:pk>/arquivar/", views.ClienteArquivarView.as_view(), name="arquivar"),
    path("<int:pk>/reativar/", views.ClienteReativarView.as_view(), name="reativar"),
    path("<int:pk>/excluir/", views.ClienteExcluirView.as_view(), name="excluir"),
]
