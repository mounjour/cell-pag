"""
Configurações do projeto — Sistema de Acompanhamento de Pagamentos de Celulares.

Valores sensíveis e específicos de ambiente vêm do arquivo `.env` (via django-environ).
Ver `.env.example` para a lista de variáveis.
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY_INSEGURA = "dev-inseguro-troque-no-.env"

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

# ── Núcleo ────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY", default=SECRET_KEY_INSEGURA)
DEBUG = env("DEBUG")

# Em produção a SECRET_KEY tem de vir do ambiente — sem ela, sessões, tokens de
# reset e assinatura de cookies ficam previsíveis.
if not DEBUG and SECRET_KEY == SECRET_KEY_INSEGURA:
    raise ImproperlyConfigured(
        "Defina SECRET_KEY no ambiente para rodar com DEBUG=False."
    )

# Descarta entradas vazias (ex.: ALLOWED_HOSTS="" no painel do provedor viraria
# [''], que o Django trataria como um host válido).
ALLOWED_HOSTS = [host.strip() for host in env("ALLOWED_HOSTS") if host.strip()]

# O Render publica o host real do serviço nesta variável. É a fonte da verdade
# em produção — não use curinga (".onrender.com" aceitaria o Host de qualquer
# app do Render). Ver docs/DEPLOY.md.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

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
    "axes",  # lockout de login por força-bruta
    "csp",   # Content-Security-Policy
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
    "csp.middleware.CSPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Registra o usuário logado em cada alteração auditada (Fase 3).
    "auditlog.middleware.AuditlogMiddleware",
    # django-axes: precisa vir por último (depois do AuthenticationMiddleware).
    "axes.middleware.AxesMiddleware",
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
    # Reaproveita a conexão por 10 min em vez de abrir uma por request.
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=600)
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

# django-axes intercepta a autenticação antes do backend padrão do Django.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Lockout de força-bruta no login. Trava a combinação usuário+IP: mesmo que o
# site esteja atrás do proxy do Render (IP do cliente = IP do proxy), o efeito
# prático vira "trava por usuário" — e travar um usuário conhecido já inviabiliza
# o chute online, sem risco de travar todo mundo por um IP compartilhado.
# Reset manual: python manage.py axes_reset_username <nome>
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=8)
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_HOURS", default=1)  # horas
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = True
AXES_VERBOSE = not DEBUG
AXES_LOCKOUT_TEMPLATE = None  # resposta HTTP 429 padrão, sem template dedicado

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sessão de app financeiro — expira em 12 h por padrão (ajustável por env).
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 12)
SESSION_SAVE_EVERY_REQUEST = True  # renova a validade a cada request ativo

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
# collectstatic). O storage com manifesto põe um hash no nome de cada arquivo
# (base.<hash>.css) — assim uma mudança de CSS/JS invalida o cache do navegador
# sozinha, sem o usuário precisar dar "recarregar forçado".
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Telefone (django-phonenumber-field) ───────────────────────────────────────
PHONENUMBER_DEFAULT_REGION = "BR"
PHONENUMBER_DB_FORMAT = "E164"  # guarda +55... — formato exigido pela API do WhatsApp

# ── Lembrete diário no WhatsApp da Yslane (Fase 2, Modalidade A) ──────────────
# Número em E.164 (ex.: +5583988887777). O envio de verdade sai pela Evolution
# API quando WHATSAPP_PROVIDER=evolution — ver apps/pagamentos/lembrete.py.
YSLANE_WHATSAPP_NUMERO = env("YSLANE_WHATSAPP_NUMERO", default="")

# WhatsApp via Evolution API (substitui a WhatsApp Cloud API da Meta). "log"
# prepara a fila sem enviar; "evolution" dispara as mensagens de verdade quando
# EVOLUTION_API_URL / _API_KEY / _INSTANCE estiverem preenchidos.
WHATSAPP_PROVIDER = env("WHATSAPP_PROVIDER", default="log")
WHATSAPP_PIX_CHAVE = env("WHATSAPP_PIX_CHAVE", default="")
EVOLUTION_API_URL = env("EVOLUTION_API_URL", default="")
EVOLUTION_API_KEY = env("EVOLUTION_API_KEY", default="")
EVOLUTION_INSTANCE = env("EVOLUTION_INSTANCE", default="")
# Token compartilhado que autentica o webhook de status da Evolution.
EVOLUTION_WEBHOOK_TOKEN = env("EVOLUTION_WEBHOOK_TOKEN", default="")

# Cobrança Pix via Cora (Fase 7). O padrão "log" não chama o banco.
CORA_PROVIDER = env("CORA_PROVIDER", default="log")
CORA_CLIENT_ID = env("CORA_CLIENT_ID", default="")
CORA_CERT_PATH = env("CORA_CERT_PATH", default="")
CORA_KEY_PATH = env("CORA_KEY_PATH", default="")
CORA_TOKEN_URL = env("CORA_TOKEN_URL", default="")
CORA_API_BASE_URL = env("CORA_API_BASE_URL", default="")
# Token compartilhado exigido no webhook da Cora (via ?token= na URL cadastrada).
CORA_WEBHOOK_TOKEN = env("CORA_WEBHOOK_TOKEN", default="")

# ── Segurança (aplicada quando DEBUG=False) ───────────────────────────────────
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HSTS — padrão de 1 dia (o host atual não tem subdomínios, então
    # include-subdomains é inócuo e recomendado). Ao migrar para um domínio
    # próprio e estável, suba SECURE_HSTS_SECONDS para 31536000 (1 ano) e só aí
    # ligue SECURE_HSTS_PRELOAD — preload é praticamente irreversível.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=86400)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
    if RENDER_EXTERNAL_HOSTNAME:
        origem_render = f"https://{RENDER_EXTERNAL_HOSTNAME}"
        if origem_render not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origem_render)

# ── Content-Security-Policy (django-csp) ─────────────────────────────────────
# Não há <script> nem <style> inline no projeto — só alguns `style="margin…"`
# em atributo, por isso style-src mantém 'unsafe-inline'. script-src é 'self'
# puro: um <script> ou on*=… injetado não executa.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "frame-ancestors": ["'none'"],
        "form-action": ["'self'"],
    },
}

# ── Logs ─────────────────────────────────────────────────────────────────────
# Tudo para o console (stdout) — é o que o Render captura, tanto do serviço web
# quanto das execuções de cron (a rotina diária). Nível ajustável por env.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simples": {"format": "{asctime} {levelname} {name} — {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simples"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # Fluxo de cobrança/lembrete/Pix: INFO por padrão para a rotina diária
        # deixar rastro do que preparou e enviou.
        "pagamentos": {
            "handlers": ["console"],
            "level": env("LOG_LEVEL_PAGAMENTOS", default="INFO"),
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": env("LOG_LEVEL_DJANGO", default="INFO"),
            "propagate": False,
        },
    },
}
