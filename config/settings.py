"""
Configurações do projeto — Sistema de Acompanhamento de Pagamentos de Celulares.

Valores sensíveis e específicos de ambiente vêm do arquivo `.env` (via django-environ).
Ver `.env.example` para a lista de variáveis.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

# ── Núcleo ────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY", default="dev-inseguro-troque-no-.env")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ── Aplicações ────────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "phonenumber_field",
    "import_export",
    "auditlog",
]

LOCAL_APPS = [
    "apps.usuarios",
    "apps.clientes",
    "apps.contratos",
    "apps.pagamentos",
    "apps.relatorios",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Registra o usuário logado em cada alteração auditada (Fase 3).
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ── Banco de dados ────────────────────────────────────────────────────────────
# Dev: SQLite por padrão. Produção: definir DATABASE_URL (postgres://...) no .env.
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ── Autenticação ──────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "usuarios.Usuario"

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "clientes:lista"
LOGOUT_REDIRECT_URL = "usuarios:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internacionalização ───────────────────────────────────────────────────────
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ── Arquivos estáticos e de mídia ─────────────────────────────────────────────
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# WhiteNoise serve os estáticos em produção a partir de STATIC_ROOT (após
# collectstatic). O storage com hash/manifesto entra no endurecimento de deploy.
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Telefone (django-phonenumber-field) ───────────────────────────────────────
PHONENUMBER_DEFAULT_REGION = "BR"
PHONENUMBER_DB_FORMAT = "E164"  # guarda +55... — formato exigido pela API do WhatsApp

# ── Lembrete diário no WhatsApp da Yslane (Fase 2, Modalidade A) ──────────────
# Número em E.164 (ex.: +5583988887777). O envio de verdade (Cloud API/BSP)
# entra quando existir conta WhatsApp Business — ver apps/pagamentos/lembrete.py.
YSLANE_WHATSAPP_NUMERO = env("YSLANE_WHATSAPP_NUMERO", default="")

# WhatsApp Cloud API (Fase 6). "log" prepara a fila sem enviar; "meta" ativa
# mensagens-template oficiais quando todas as credenciais estiverem presentes.
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="log")
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", default="")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_WEBHOOK_VERIFY_TOKEN = env("WHATSAPP_WEBHOOK_VERIFY_TOKEN", default="")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")
WHATSAPP_PIX_CHAVE = env("WHATSAPP_PIX_CHAVE", default="")
WHATSAPP_TEMPLATE_VENCIMENTO = env("WHATSAPP_TEMPLATE_VENCIMENTO", default="cobranca_vencimento")
WHATSAPP_TEMPLATE_ATRASO = env("WHATSAPP_TEMPLATE_ATRASO", default="cobranca_atraso")
WHATSAPP_TEMPLATE_BLOQUEIO = env("WHATSAPP_TEMPLATE_BLOQUEIO", default="cobranca_bloqueio")

# Cobrança Pix dinâmica via Cora (Fase 7). O padrão "log" não chama o banco.
CORA_PROVIDER = env("CORA_PROVIDER", default="log")
CORA_CLIENT_ID = env("CORA_CLIENT_ID", default="")
CORA_CERT_PATH = env("CORA_CERT_PATH", default="")
CORA_KEY_PATH = env("CORA_KEY_PATH", default="")
CORA_TOKEN_URL = env("CORA_TOKEN_URL", default="")
CORA_API_BASE_URL = env("CORA_API_BASE_URL", default="")

# ── Segurança (aplicada quando DEBUG=False) ───────────────────────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
