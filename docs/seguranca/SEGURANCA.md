# Revisão de segurança — pontos a tratar

Levantamento inicial (branch `seguranca/hardening-revisao`). Cada item é uma
caixa a resolver; a ordem é por prioridade, não por esforço.

**Feito nesta branch:** todos os 17 itens — ver os commits `seguranca:`.
Pendências que não são código: habilitar Dependabot nas Settings do repo (12) e
adicionar um disco persistente no Render para os anexos (2).

**Passos de painel/conta (GitHub, Render, senhas, LGPD):**
[`SEGURANCA-OPERACIONAL.md`](SEGURANCA-OPERACIONAL.md) — runbook do que só o
Alisson faz. LGPD (aviso de privacidade, retenção de anexos, pedido do titular):
[`LGPD.md`](LGPD.md).

**Depois da branch:** a tela de bloqueio do `django-axes` deixou de ser o
HTTP 429 cru — `AXES_LOCKOUT_TEMPLATE = "usuarios/bloqueado.html"` mostra uma
página "Muitas tentativas" com o tempo de espera e como liberar. Status
continua 429.

## Já está bem resolvido (linha de base)

- Templates com autoescape; **nenhum** `mark_safe` / `|safe` / `format_html` no código.
- Só ORM — nenhum `raw()`, `cursor.execute`, `.extra()`, `eval`, `subprocess`.
- CSRF ativo; middlewares de segurança/clickjacking no lugar (`X-Frame-Options: DENY`).
- `manage.py check --deploy` com `DEBUG=False` sai quase limpo (ver itens 8 e 10).
- Webhook da Evolution autenticado por token com `hmac.compare_digest`.
- Segredos fora do Git (`.gitignore` cobre `.env`, `.env.*`, `*.pem`); `SECRET_KEY` gerada pelo Render.
- Usuário customizado desde o início; trilha de auditoria (`django-auditlog`).
- Período de relatório limitado a 367 dias (evita PDF/planilha gigante).
- Relatórios restritos a `dono` (`DonoRequeridoMixin`).

---

## Alta — antes de deixar o site público

### 1. `ALLOWED_HOSTS` com curinga de subdomínio — ✅ feito
`render.yaml` definia `ALLOWED_HOSTS=".onrender.com"`, que aceitava o header
`Host` de **qualquer** `*.onrender.com`. Removido do `render.yaml`; agora o host
vem só do `RENDER_EXTERNAL_HOSTNAME`. `settings.py` também descarta entradas
vazias da lista.

### 2. Upload de arquivo sem validação — ✅ feito
`apps/validadores.py`: os dois `FileField` (`Pagamento.comprovante`,
`DocumentoContrato.arquivo`) só aceitam `pdf/jpg/jpeg/png/webp` até 10 MB
(migrações `pagamentos.0006`, `contratos.0008`).
`apps/arquivos.servir_anexo` + as views `pagamentos:comprovante` /
`contratos:documento_baixar` (com login) entregam o arquivo **sempre como
`attachment`**, com `X-Content-Type-Options: nosniff` e
`Content-Security-Policy: default-src 'none'; sandbox`. A rota pública de mídia
(`static(MEDIA_URL)` no DEBUG) foi removida.
**Ainda falta (infra, não código):** disco persistente no Render — sem ele os
anexos continuam sumindo a cada deploy (bug funcional, não de segurança).

### 3. Login sem proteção a força-bruta — ✅ feito
`django-axes` (8.3.1): trava a combinação `usuário+IP` após 8 falhas (`AXES_FAILURE_LIMIT`)
por 1 h (`AXES_COOLOFF_HOURS`), zera no sucesso. Atrás do proxy do Render o
efeito é "trava por usuário" — sem risco de travar todo mundo por um IP.
Destravar: `python manage.py axes_reset_username <nome>`.

---

## Média

### 4. PII em log de nível INFO — ✅ feito
`whatsapp.py` / `lembrete.py`: no INFO o telefone sai mascarado (`…7777`) e o
texto da mensagem não sai — o conteúdo completo foi para o nível DEBUG.
`mascara_numero()` em `whatsapp.py` é o utilitário compartilhado.

### 5. Erro da Cora vaza para a tela — ✅ feito
`cora_api` (e `whatsapp.py`) agora logam o corpo da resposta (até 500 chars) no
servidor e levantam só uma mensagem curta (`"A Cora recusou a requisição (HTTP
NNN)."`), que é o que chega em `CobrancaCora.erro` / `Cobranca.erro` e nas telas.

### 6. Injeção de fórmula no Excel exportado — ✅ feito
`apps/relatorios/views.py`: `_celula()` prefixa `'` em texto que começa com
`= + - @` (nome do cliente / apelido). O PDF usa `Table` com strings simples,
que **não** interpreta marcação — sem ação necessária lá.

### 7. Webhook da Cora sem autenticação — ✅ feito
`/pagamentos/webhooks/cora/` agora exige `CORA_WEBHOOK_TOKEN` (via `?token=` na
URL cadastrada, ou header `apikey`/`Authorization`), com `hmac.compare_digest`.
Sem token configurado só responde com `DEBUG=True`.

### 8. `SECRET_KEY` com fallback inseguro — ✅ feito
`settings.py` agora levanta `ImproperlyConfigured` quando `not DEBUG` e a
`SECRET_KEY` ainda é a de desenvolvimento.

### 9. Python 3.12.7 no Render — ✅ feito
`render.yaml` passou para `PYTHON_VERSION=3.12.10` (site e cron). Rever
periodicamente para o último 3.12.x.

### 10. HSTS curto e sem preload — ✅ parcial
`SECURE_HSTS_SECONDS` subiu de 3600 para 86400 (1 dia) e virou tunável por env;
`include-subdomains` continua ligado (o host não tem subdomínios).
**Falta:** em domínio próprio e estável, subir para `31536000` e ligar
`SECURE_HSTS_PRELOAD` (irreversível — só quando tiver certeza). O aviso `W021`
do `check --deploy` é esperado até lá.

---

## Baixa — defesa em profundidade

### 11. Sem Content-Security-Policy — ✅ feito
`django-csp` (4.0): `default-src 'self'`, `script-src 'self'` (um `<script>` ou
`on*=` injetado não executa), `object-src`/`frame-ancestors` `'none'`,
`base-uri`/`form-action` `'self'`. `style-src` mantém `'unsafe-inline'` só por
causa de alguns `style="margin…"` em atributo — inline **script** já está barrado.

### 12. Sem varredura de dependência — ✅ feito
`.github/dependabot.yml`: varredura `pip` semanal (+ `github-actions`). Abre PR
quando sai correção. Precisa do Dependabot habilitado nas Settings do repo.

### 13. Política de senha
`MinimumLengthValidator` em `min_length: 8` (padrão do Django) — por decisão do
Alisson, voltou de 12 para 8. Os demais validadores (comum, só-números,
parecida com o usuário) seguem ativos.

### 14. Sessão longa — ✅ feito
`SESSION_COOKIE_AGE` = 12 h (tunável por env) + `SESSION_SAVE_EVERY_REQUEST`
(renova enquanto houver uso).

### 15. `filename` do upload interpolado direto no `upload_to`
O Django moderno já barra `..`; normalizar o nome é defesa a mais.

### 16. Import do admin faz upsert por CPF
`import_id_fields=("cpf",)` — CSV malicioso sobrescreve clientes por CPF.
Staff-only, risco baixo — ciente.

### 17. Premissa de acesso
Todo usuário autenticado vê todos os registros (ferramenta interna de 2
pessoas). Não há checagem por objeto — **IDOR não se aplica** por decisão de
projeto. Registrado para não ser confundido com falha.
