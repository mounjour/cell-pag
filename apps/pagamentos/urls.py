from django.urls import path

from . import views

app_name = "pagamentos"

urlpatterns = [
    path("", views.CobrarHojeView.as_view(), name="cobrar_hoje"),
]
