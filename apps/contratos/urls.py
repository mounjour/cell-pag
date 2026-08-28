from django.urls import path

from . import views

app_name = "contratos"

urlpatterns = [
    path("", views.ContratoListView.as_view(), name="lista"),
    path("novo/", views.ContratoCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.ContratoDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.ContratoUpdateView.as_view(), name="editar"),
    path(
        "<int:contrato_pk>/documentos/novo/",
        views.DocumentoCreateView.as_view(),
        name="documento_novo",
    ),
]
