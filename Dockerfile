# Imagem de produção do site (usada pelo Coolify na VPS — ver docs/deploy/DEPLOY-VPS.md).
# Segredos NUNCA entram na imagem: chegam por variáveis de ambiente no Coolify.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependências primeiro: a camada só é refeita quando o requirements.txt muda.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Estáticos servidos pelo WhiteNoise. Valores fictícios só para o comando rodar
# no build (o settings.py exige SECRET_KEY real quando DEBUG=False).
RUN SECRET_KEY=somente-para-o-build DEBUG=False python manage.py collectstatic --noinput

# Roda sem privilégio de root. /app/media é o volume dos anexos (comprovantes,
# documentos) — precisa ser gravável pelo usuário do site.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media \
    && sed -i 's/\r$//' deploy/entrypoint.sh \
    && chmod +x deploy/entrypoint.sh \
    && chown -R app:app /app/media /app/staticfiles
USER app

EXPOSE 8000

# Saudável = a tela de login responde 200. Manda o Host de ALLOWED_HOSTS e
# X-Forwarded-Proto: https, senão o SECURE_SSL_REDIRECT/ALLOWED_HOSTS de produção
# recusariam a chamada local. start-period cobre as migrações do entrypoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3     CMD python -c "import os, urllib.request as u; h = (os.environ.get('ALLOWED_HOSTS') or 'localhost').split(',')[0].strip(); u.urlopen(u.Request('http://127.0.0.1:8000/entrar/', headers={'Host': h, 'X-Forwarded-Proto': 'https'}), timeout=5)"
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
# O log de acesso usa %(U)s (caminho sem query string): os webhooks autenticam por
# ?token=, que não pode ir parar nos logs. gthread evita que uma chamada lenta à
# Cora (webhook) trave um worker inteiro.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "gthread", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--access-logformat", "%(h)s %(l)s %(u)s %(t)s \"%(m)s %(U)s\" %(s)s %(b)s %(L)ss"]
