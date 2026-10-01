from django.urls import path

from . import views

app_name = "contratos"

urlpatterns = [
    path("previsao/", views.ContratoPrevisaoView.as_view(), name="previsao"),
    path("importar/", views.PlanilhaPreviaView.as_view(), name="importar_previa"),
    path("importar/enviar-pendencias/", views.ImportarPendenciasView.as_view(), name="importar_pendencias"),
    path("importar/pendencias/", views.ImportacaoPendenciasView.as_view(), name="importacao_pendencias"),
    path("importar/pendencias/<int:pk>/", views.ResolverImportacaoView.as_view(), name="resolver_importacao"),
    path("", views.ContratoListView.as_view(), name="lista"),
    path("novo/", views.ContratoCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.ContratoDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.ContratoUpdateView.as_view(), name="editar"),
    path("<int:pk>/quitar/", views.ContratoQuitarView.as_view(), name="quitar"),
    path(
        "<int:pk>/gerar-vencimentos/",
        views.ContratoGerarVencimentosView.as_view(),
        name="gerar_vencimentos",
    ),
    path(
        "<int:contrato_pk>/documentos/novo/",
        views.DocumentoCreateView.as_view(),
        name="documento_novo",
    ),
    path(
        "documentos/<int:pk>/baixar/",
        views.DocumentoDownloadView.as_view(),
        name="documento_baixar",
    ),
]
