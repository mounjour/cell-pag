# Deploy no Render + rotina diária automática

Este guia coloca o sistema no ar no [Render](https://render.com) com:

- **site** (Gunicorn + WhiteNoise) em `https://cell-pag.onrender.com`;
- **PostgreSQL** gerenciado;
- **cron diário** que roda `manage.py rotina_diaria` às 08:30 (horário de Brasília):
  gera as parcelas, monta o lembrete da Yslane e prepara/dispara as cobranças.

O [`render.yaml`](../render.yaml) na raiz descreve os três de uma vez (Blueprint).

---

## 0. O que só você pode fazer (não dá para automatizar)

| Item | Onde | Necessário para |
|---|---|---|
| Criar conta no Render e conectar este repositório do GitHub | render.com | tudo |
| Conta **WhatsApp Business** verificada na Meta + 3 templates aprovados | business.facebook.com | envio real de lembrete/cobrança — ver [`WHATSAPP.md`](WHATSAPP.md) |
| Contratar **CoraPro** + gerar certificado mTLS | app/Web da Cora | geração real de Pix — ver [`CORA.md`](CORA.md) |

Enquanto (2) e (3) não estiverem prontos, o sistema fica com
`WHATSAPP_PROVIDER=log` e `CORA_PROVIDER=log`: **tudo funciona, mas nada sai
do sistema** (fila montada, nada enviado, nenhum Pix criado). Dá para subir
para produção assim e ligar os canais depois, só trocando variáveis no painel.

---

## 1. Subir o código

```bash
git add .
git commit -m "Deploy: rotina diária + configs do Render"
git push
```

## 2. Criar tudo pelo Blueprint

1. Render → **New** → **Blueprint**.
2. Aponte para o repositório `cell-pag`. O Render lê o `render.yaml` e mostra:
   - serviço web `cell-pag`
   - cron `cell-pag-rotina-diaria`
   - banco `cell-pag-db`
   - grupo de variáveis `cell-pag-config`
3. **Apply**. O primeiro build roda `pip install`, `collectstatic` e, no
   `preDeployCommand`, o `migrate`.

## 3. Preencher as variáveis marcadas `sync: false`

No painel do grupo **cell-pag-config**, preencha (pode deixar em branco o que
ainda não tem — o modo `log` não exige):

| Variável | Valor agora |
|---|---|
| `YSLANE_WHATSAPP_NUMERO` | número da Yslane em E.164, ex.: `+5583988887777` |
| `WHATSAPP_PROVIDER` | `log` (troque para `meta` quando os templates forem aprovados) |
| `WHATSAPP_*` (demais) | em branco por enquanto — ver [`WHATSAPP.md`](WHATSAPP.md) |
| `CORA_PROVIDER` | `log` (troque para `cora` quando tiver CoraPro) |
| `CORA_*` (demais) | em branco por enquanto — ver [`CORA.md`](CORA.md) |

`SECRET_KEY` é gerada automaticamente. `DATABASE_URL`, `ALLOWED_HOSTS` e
`CSRF_TRUSTED_ORIGINS` já se resolvem sozinhas no Render
(`RENDER_EXTERNAL_HOSTNAME`).

> **Certificado da Cora:** o Render não tem sistema de arquivos persistente para
> subir `.pem` pelo painel. Quando for ativar a Cora, use um
> [Secret File](https://render.com/docs/configure-environment-variables#secret-files)
> no serviço web **e** no cron, e aponte `CORA_CERT_PATH` / `CORA_KEY_PATH` para
> o caminho do secret file (ex.: `/etc/secrets/cora-cert.pem`).

## 4. Primeiro acesso

Abra um **Shell** no serviço web (aba *Shell* do Render) e crie o login:

```bash
python manage.py createsuperuser
```

Ou, para popular dados de teste:

```bash
python manage.py seed_demo
```

Acesse `https://cell-pag.onrender.com/entrar/`.

---

## 5. Como a rotina diária funciona

O cron `cell-pag-rotina-diaria` roda todo dia às **11:30 UTC = 08:30 America/Sao_Paulo**
(o Brasil não tem mais horário de verão, então o offset é fixo em −3h):

```bash
python manage.py rotina_diaria
```

Que executa, **nesta ordem**:

1. `gerar_vencimentos` — para cada contrato não quitado, cria as parcelas que
   faltam até 60 dias à frente, recalcula a data prevista de quitação e
   sincroniza o `status` salvo com o calculado.
2. `enviar_lembrete_diario` — monta o resumo "quem cobrar hoje" e manda para o
   WhatsApp da Yslane (ou só loga, em modo `log`).
3. `enviar_cobrancas_clientes` — reconcilia as cobranças Pix abertas na Cora,
   cria o Pix que falta e prepara/envia as mensagens de vencimento/atraso do dia.

Se uma etapa falhar, as outras ainda rodam e a execução termina com erro
(o Render marca a run como *failed* e fica no histórico do cron).

### Testar sem esperar o horário

Na aba *Shell*, ou localmente:

```bash
python manage.py rotina_diaria --hoje 2026-10-01        # simula outro dia
python manage.py rotina_diaria --sem-cobrancas          # só vencimentos + lembrete
```

### Mudar o horário

Edite `schedule` no `render.yaml` (sintaxe cron, em **UTC**) e faça push, ou
altere direto em *Settings* do cron no painel. `30 11 * * *` = 08:30 BRT.

### Rodar o gerador de parcelas fora da rotina

Não é mais necessário no dia a dia: **ao cadastrar/editar um contrato com valor
da parcela preenchido, as parcelas já são geradas na hora**. O botão "Gerar
parcelas" na tela do contrato e o comando `gerar_vencimentos` continuam
disponíveis como reforço.

### Conciliação da Cora mais de uma vez por dia (opcional)

Se quiser detectar pagamentos Pix mais rápido, crie um segundo cron
(ex.: `0 * * * *`) com:

```bash
python manage.py reconciliar_cora
```

---

## 6. Custos (referência, planos do Render em 2025)

| Recurso | Plano free | Plano pago mínimo |
|---|---|---|
| Site (web) | dorme após 15 min ocioso, acorda em ~1 min | Starter ~US$ 7/mês (sempre ligado) |
| PostgreSQL | **expira em 30 dias** | Basic ~US$ 7/mês |
| Cron job | — | ~US$ 1/mês (por uso) |

Para avaliação, o free resolve. Para uso diário de verdade, conte com
**~US$ 15/mês**. Migrar de free para pago não exige mudar código.

---

## 7. Checklist de ativação dos canais (depois)

**WhatsApp** (detalhe em [`WHATSAPP.md`](WHATSAPP.md)):

- [ ] Conta WhatsApp Business verificada + número comercial
- [ ] Templates `cobranca_vencimento`, `cobranca_atraso`, `cobranca_bloqueio` aprovados em `pt_BR`
- [ ] Variáveis `WHATSAPP_GRAPH_VERSION`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_PIX_CHAVE` preenchidas
- [ ] Webhook `https://cell-pag.onrender.com/pagamentos/webhooks/whatsapp/` cadastrado na Meta
- [ ] `WHATSAPP_PROVIDER=meta`

**Cora** (detalhe em [`CORA.md`](CORA.md)):

- [ ] CoraPro contratado + Integração Direta liberada
- [ ] Certificado/chave mTLS como Secret Files no web **e** no cron
- [ ] `CORA_CLIENT_ID`, `CORA_CERT_PATH`, `CORA_KEY_PATH`, `CORA_TOKEN_URL`, `CORA_API_BASE_URL` preenchidas (Stage primeiro, depois produção)
- [ ] Webhook `https://cell-pag.onrender.com/pagamentos/webhooks/cora/` cadastrado (recurso `invoice`, gatilhos `paid`/`overdue`/`canceled`)
- [ ] `CORA_PROVIDER=cora`

Depois de trocar cada `PROVIDER`, rode `python manage.py rotina_diaria --sem-cobrancas`
primeiro (confere que nada quebrou) e só então deixe a cobrança automática ativa.
