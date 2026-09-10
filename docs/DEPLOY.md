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
| Subir uma instância da **Evolution API** (Docker) e conectar um número por QR Code | servidor próprio | envio real de lembrete/cobrança — ver [`WHATSAPP.md`](WHATSAPP.md) |
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
| `WHATSAPP_PROVIDER` | `log` (troque para `evolution` quando a instância estiver conectada) |
| `WHATSAPP_PIX_CHAVE`, `EVOLUTION_*` | em branco por enquanto — ver [`WHATSAPP.md`](WHATSAPP.md) |
| `CORA_PROVIDER` | `log` (troque para `cora` quando tiver CoraPro) |
| `CORA_*` (demais) | em branco por enquanto — ver [`CORA.md`](CORA.md) |

`SECRET_KEY` é gerada automaticamente (e o app **recusa** subir com `DEBUG=False`
sem ela). `DATABASE_URL`, `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` se resolvem
sozinhos no Render via `RENDER_EXTERNAL_HOSTNAME` — **não** defina `ALLOWED_HOSTS`
com curinga (`.onrender.com`); se usar domínio próprio, coloque o host exato.

> **Certificado da Cora:** o Render não tem sistema de arquivos persistente para
> subir `.pem` pelo painel. Quando for ativar a Cora, use um
> [Secret File](https://render.com/docs/configure-environment-variables#secret-files)
> no serviço web **e** no cron, e aponte `CORA_CERT_PATH` / `CORA_KEY_PATH` para
> o caminho do secret file (ex.: `/etc/secrets/cora-cert.pem`).

> **Anexos (comprovantes, documentos):** o disco do container é efêmero — sem um
> [Persistent Disk](https://render.com/docs/disks) montado em `MEDIA_ROOT`
> (`/opt/render/project/src/media`), os arquivos enviados somem a cada deploy.
> A validação (pdf/jpg/png/webp até 10 MB) e a entrega autenticada já estão no
> código; falta só o disco quando quiserem guardar anexos de verdade.

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

## 6. Custos (referência, planos do Render em 2026)

O Render cobra em dois níveis que se somam: a **assinatura do workspace** (fixa) e
o **preço de cada recurso** por tamanho de instância. Para este projeto o workspace
**Hobby (grátis)** basta — nada aqui exige o plano Pro (US$ 25/mês: SOC 2,
autoscaling, mais banda). O uso de banda de uma ferramenta interna para 2 pessoas
fica folgado no Hobby.

### O que o `render.yaml` provisiona

| Recurso | Como está no blueprint | Custo/mês |
|---|---|---|
| Workspace | Hobby | US$ 0 |
| Site (web) `cell-pag` | `plan: starter` — obrigatório: tem disco (o free não monta disco) e tira o cold-start | ~US$ 7 |
| Disco persistente (anexos) | `sizeGB: 1` — US$ 0,25/GB | ~US$ 0,25 |
| PostgreSQL `cell-pag-db` | `plan: basic-256mb` — backup diário, não expira | ~US$ 6–7 |
| Cron `cell-pag-rotina-diaria` | `plan: free` — roda ~1 min/dia | US$ 0 |
| **Total no Render** | | **≈ US$ 13–15/mês** |

Com IOF + spread de câmbio (~+6%): **≈ R$ 75–90/mês**. Mais a retenção de US$ 1
na validação do cartão no cadastro. Pagamento só em cartão internacional — o
Render não aceita Pix nem boleto.

### Fora dessa conta

- **Evolution API (WhatsApp)** — não roda no Render; é Docker em servidor próprio
  (item 0). Com `WHATSAPP_PROVIDER=log`, custo zero. Para ativar de verdade: um
  VPS pequeno (~US$ 4–6/mês) ou uma VM que já exista.
- **CoraPro** — assinatura do banco Cora para gerar Pix via API; custo bancário,
  não de infraestrutura. Com `CORA_PROVIDER=log`, custo zero.
- **Sentry** — o tier grátis atende.

### Free não serve para produção aqui

- **Postgres free** expira em 30 dias e some — inaceitável para registro
  financeiro (por isso o blueprint fixa `basic-256mb`).
- **Web free** dorme após 15 min, volta em ~1 min e **não monta disco** — os
  anexos sumiriam a cada deploy. A Yslane usa todo dia no celular.

Para avaliação rápida, dá para trocar tudo para free e voltar depois sem mexer no
código. Para uso diário de verdade, conte com **~US$ 15/mês** no Render.

---

## 7. Checklist de ativação dos canais (depois)

**WhatsApp** (detalhe em [`WHATSAPP.md`](WHATSAPP.md)):

- [ ] Instância da Evolution API no ar + número conectado por QR Code
- [ ] Variáveis `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`, `EVOLUTION_WEBHOOK_TOKEN`, `WHATSAPP_PIX_CHAVE` preenchidas
- [ ] Webhook `messages.update` → `https://cell-pag.onrender.com/pagamentos/webhooks/whatsapp/` cadastrado na Evolution, autenticado pelo `EVOLUTION_WEBHOOK_TOKEN`
- [ ] `WHATSAPP_PROVIDER=evolution`

**Cora** (detalhe em [`CORA.md`](CORA.md)):

- [ ] CoraPro contratado + Integração Direta liberada
- [ ] Certificado/chave mTLS como Secret Files no web **e** no cron
- [ ] `CORA_CLIENT_ID`, `CORA_CERT_PATH`, `CORA_KEY_PATH`, `CORA_TOKEN_URL`, `CORA_API_BASE_URL` preenchidas (Stage primeiro, depois produção)
- [ ] Webhook `https://cell-pag.onrender.com/pagamentos/webhooks/cora/` cadastrado (recurso `invoice`, gatilhos `paid`/`overdue`/`canceled`)
- [ ] `CORA_PROVIDER=cora`

Depois de trocar cada `PROVIDER`, rode `python manage.py rotina_diaria --sem-cobrancas`
primeiro (confere que nada quebrou) e só então deixe a cobrança automática ativa.
