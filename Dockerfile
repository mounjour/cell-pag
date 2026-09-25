# Imagem de produção do site (usada pelo Coolify na VPS — ver docs/DEPLOY-VPS.md).
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
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
