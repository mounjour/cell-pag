from django.urls import path

from . import views

app_name = "aparelhos"

urlpatterns = [
    path("", views.AparelhoListView.as_view(), name="lista"),
    path("importar/", views.AparelhoImportarView.as_view(), name="importar"),
    path("importar/confirmar/", views.AparelhoImportarConfirmarView.as_view(), name="importar_confirmar"),
    path("novo/", views.AparelhoCreateView.as_view(), name="novo"),
    path("<int:pk>/", views.AparelhoDetailView.as_view(), name="detalhe"),
    path("<int:pk>/editar/", views.AparelhoUpdateView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.AparelhoExcluirView.as_view(), name="excluir"),
]
