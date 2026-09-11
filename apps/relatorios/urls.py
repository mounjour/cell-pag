from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("inicio/", views.InicioView.as_view(), name="inicio"),
    path("", views.RelatorioView.as_view(), name="painel"),
    path("excel/", views.RelatorioExcelView.as_view(), name="excel"),
    path("pdf/", views.RelatorioPDFView.as_view(), name="pdf"),
]
