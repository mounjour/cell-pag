from django.contrib.auth import views as auth_views
from django.urls import path

app_name = "usuarios"

urlpatterns = [
    path(
        "entrar/",
        auth_views.LoginView.as_view(template_name="usuarios/login.html"),
        name="login",
    ),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
]
