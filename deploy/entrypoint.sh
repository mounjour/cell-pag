#!/bin/sh
# Preparação do container antes de iniciar o site (ou um comando avulso).
set -e

# Certificado e chave da Cora (mTLS): o código lê ARQUIVOS (CORA_CERT_PATH /
# CORA_KEY_PATH), mas segredo não vai na imagem nem no repositório. Eles chegam
# em base64 nas variáveis CORA_CERT_B64 / CORA_KEY_B64 e viram arquivos aqui,
# com permissão restrita. Os caminhos ficam nas variáveis CORA_CERT_PATH e
# CORA_KEY_PATH configuradas no Coolify (assim as tarefas agendadas, que rodam
# com `docker exec`, também enxergam os mesmos arquivos).
if [ -n "$CORA_CERT_B64" ] && [ -n "$CORA_KEY_B64" ]; then
  destino_cert="${CORA_CERT_PATH:-/tmp/cora/certificate.pem}"
  destino_chave="${CORA_KEY_PATH:-/tmp/cora/private-key.key}"
  mkdir -p "$(dirname "$destino_cert")" "$(dirname "$destino_chave")"
  printf '%s' "$CORA_CERT_B64" | base64 -d > "$destino_cert"
  printf '%s' "$CORA_KEY_B64" | base64 -d > "$destino_chave"
  chmod 600 "$destino_cert" "$destino_chave"
fi

# Migrações antes de subir o servidor (uma instância só, então não há corrida).
# Desligue com RUN_MIGRATIONS=0 se um dia houver mais de uma réplica.
if [ "$1" = "gunicorn" ] && [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

exec "$@"
