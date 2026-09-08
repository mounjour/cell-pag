# Revisão de segurança — pontos a tratar

Levantamento inicial (branch `seguranca/hardening-revisao`). Cada item é uma
caixa a resolver; a ordem é por prioridade, não por esforço.

**Feito nesta branch (config, sem dependência nova):** 1, 8, 9, 10, 13, 14 —
ver commit "seguranca: hardening de configuração".

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

### 2. Upload de arquivo sem validação
`Pagamento.comprovante` e `DocumentoContrato.arquivo` são `FileField` sem
checagem de extensão, tipo MIME nem tamanho. Hoje o risco é baixo porque em
produção **nada serve `MEDIA/`** (os arquivos nem baixam — e somem a cada
deploy, bug à parte). No dia que habilitarem disco persistente + rota de mídia,
vira **XSS armazenado / hospedagem de malware** (subir `.html`, `.svg`).
**Ação (antes de servir mídia):** `FileExtensionValidator` (pdf/jpg/png), limite
de tamanho no form, e servir por uma view autenticada com
`Content-Disposition: attachment` + `X-Content-Type-Options: nosniff`.

### 3. Login sem proteção a força-bruta
`auth_views.LoginView` puro, sem rate-limit nem lockout. Vai ficar exposto na
internet com 2 usuários de senha fraca em potencial.
**Ação:** `django-axes` (lockout por IP/usuário) ou throttling no proxy.

---

## Média

### 4. PII em log de nível INFO
`apps/pagamentos/whatsapp.py` e `lembrete.py` logam telefone + texto completo da
mensagem (nome do cliente, chave Pix, copia-e-cola) no stdout → logs do Render,
que ficam retidos e visíveis a quem tem acesso ao painel.
**Ação:** baixar para DEBUG, ou redigir telefone/nome, ou logar só o id da `Cobranca`.

### 5. Erro da Cora vaza para a tela
`cora_api` guarda até 1200 caracteres do corpo de resposta da Cora em
`CobrancaCora.erro`, exibido em `/pagamentos/pix/` e em "Cobrar hoje".
**Ação:** detalhe completo só no log; na tela, mensagem curta/genérica.

### 6. Injeção de fórmula no Excel/PDF exportado
Nome do cliente / apelido / observação vão crus para o `.xlsx` (openpyxl) e para
o PDF (`reportlab.Paragraph` interpreta `<b>`, `&`, `<font>`…).
**Ação:** prefixar `'` em célula que começa com `= + - @`; escapar
(`xml.sax.saxutils.escape`) os textos antes do `Paragraph`.

### 7. Webhook da Cora sem autenticação
`/pagamentos/webhooks/cora/` é escrita não autenticada (cria `EventoCora`).
Por design só registra sinal para fatura já conhecida, mas dá para endurecer.
**Ação:** aplicar o mesmo token compartilhado do webhook da Evolution.

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

### 11. Sem Content-Security-Policy
Não é nativo do Django. Como não há `<script>` inline e o CSS é do mesmo host,
dá para uma política restritiva.
**Ação:** `django-csp` com `default-src 'self'`.

### 12. Sem varredura de dependência
**Ação:** ligar Dependabot no repo (ou `pip-audit` no CI) para CVE de Django,
reportlab, etc.

### 13. Política de senha fraca — ✅ feito
`MinimumLengthValidator` agora com `min_length: 12`.

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
