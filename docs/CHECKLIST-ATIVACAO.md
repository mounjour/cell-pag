# Checklist de ativação — Cora (Pix) e Evolution API (WhatsApp)

> Estado hoje: código pronto, rodando em modo seguro (`CORA_PROVIDER=log`,
> `WHATSAPP_PROVIDER=log`). Nada é enviado, nenhum Pix é criado. Ligar = contratar
> o serviço + trocar variáveis de ambiente. Não precisa de código novo.
>
> Ordem recomendada: **1) Evolution → 2) Cora (Stage) → 3) Cora (produção)**.
> A cada `PROVIDER` trocado, rodar `manage.py rotina_diaria --sem-cobrancas` antes
> de deixar a cobrança automática ligada.

Python do venv (Windows): `.venv\Scripts\python.exe`

---

## Parte 1 — Evolution API (WhatsApp)

Software open-source e gratuito. Não se compra a API — hospeda-se. Custo = servidor.

### Contratar / hospedar
- [ ] Contratar um VPS pequeno (~R$ 20–40/mês: Hetzner, Contabo, DigitalOcean, Railway, Fly.io)
- [ ] Apontar um subdomínio com HTTPS (ex.: `evolution.sualoja.com.br`)
- [ ] Subir a Evolution API via Docker (imagem `evoapicloud/evolution-api`)
- [ ] Definir a API Key global da Evolution
- [ ] Separar um chip / número de WhatsApp DEDICADO (não usar o pessoal da Yslane)
- [ ] Criar uma instância na Evolution e conectar o número lendo o QR Code

### Configurar no projeto
- [ ] Preencher no `.env` (local) ou no grupo de variáveis do Render:
  - [ ] `WHATSAPP_PROVIDER=evolution`
  - [ ] `EVOLUTION_API_URL=https://evolution.sualoja.com.br`
  - [ ] `EVOLUTION_API_KEY=` (a chave)
  - [ ] `EVOLUTION_INSTANCE=` (nome da instância)
  - [ ] `EVOLUTION_WEBHOOK_TOKEN=` (token aleatório forte)
  - [ ] `WHATSAPP_PIX_CHAVE=` (chave Pix que aparece no texto da cobrança)
  - [ ] `YSLANE_WHATSAPP_NUMERO=+5583XXXXXXXXX` (E.164 — para o lembrete diário)
- [ ] Cadastrar na Evolution o webhook do evento `messages.update` apontando para:
      `https://cell-pag.onrender.com/pagamentos/webhooks/whatsapp/`
- [ ] Autenticar esse webhook com o mesmo `EVOLUTION_WEBHOOK_TOKEN` (header `apikey`)

### Testar
- [ ] `python manage.py enviar_cobrancas_clientes --somente-preparar` (monta a fila, não envia)
- [ ] `python manage.py rotina_diaria --sem-cobrancas` (confere que nada quebrou)
- [ ] `python manage.py enviar_cobrancas_clientes` (envia de verdade — testar com 1 contrato)
- [ ] Conferir no painel `/pagamentos/` que os status mudam para enviado / entregue / lido

Custo Parte 1: VPS ~R$ 20–40/mês · software grátis · chip pré-pago.

---

## Parte 2 — Cora (Pix automático)

A API ("Integração Direta") não é aberta. Exige o plano CoraPro + certificado mTLS.

### Contratar
- [ ] Abrir conta PJ na Cora (com o CNPJ da loja) — grátis
- [ ] Assinar o plano **CoraPro** (~R$ 44,90/mês) no app ou Cora Web
- [ ] Solicitar acesso de **Integração Direta**
- [ ] Emitir o certificado mTLS do ambiente **Stage** (homologação): arquivos `.PEM` + `.KEY`
- [ ] Guardar `certificate.pem` e `private-key.key` FORA do repositório (nunca no GitHub)

### Configurar no projeto — Stage primeiro
- [ ] Preencher no `.env` / Render:
  - [ ] `CORA_PROVIDER=cora`
  - [ ] `CORA_CLIENT_ID=` (client id da Cora)
  - [ ] `CORA_CERT_PATH=` (caminho do `.pem`)
  - [ ] `CORA_KEY_PATH=` (caminho do `.key`)
  - [ ] `CORA_TOKEN_URL=https://matls-clients.api.stage.cora.com.br/token`
  - [ ] `CORA_API_BASE_URL=https://matls-clients.api.stage.cora.com.br`
  - [ ] `CORA_WEBHOOK_TOKEN=` (token aleatório forte)
- [ ] Cadastrar o webhook na Cora:
      `https://cell-pag.onrender.com/pagamentos/webhooks/cora/?token=<CORA_WEBHOOK_TOKEN>`
  - [ ] Recurso: `invoice`
  - [ ] Gatilhos: `paid`, `overdue`, `canceled`

### No Render (produção)
- [ ] Subir `.pem` e `.key` como **Secret Files** no serviço **web**
- [ ] Subir `.pem` e `.key` como **Secret Files** também no **cron** (os dois serviços)
- [ ] Apontar `CORA_CERT_PATH` / `CORA_KEY_PATH` para `/etc/secrets/...`

### Testar no Stage
- [ ] `python manage.py criar_cobranca_teste` (cria e consulta uma cobrança de ponta a ponta)
- [ ] `python manage.py reconciliar_cora` (confere Pix abertos)
- [ ] `python manage.py rotina_diaria --sem-cobrancas` (confere que nada quebrou)
- [ ] Conferir a tela `/pagamentos/pix/` (pagos / aguardando / não pagos / erros)

### Migrar para produção
- [ ] Emitir o certificado mTLS de **produção** na Cora (par separado do Stage)
- [ ] Trocar `CORA_TOKEN_URL` e `CORA_API_BASE_URL` para as URLs de produção
- [ ] Trocar os Secret Files pelos certificados de produção (web + cron)
- [ ] Recadastrar o webhook no ambiente de produção da Cora
- [ ] Repetir `criar_cobranca_teste` + `rotina_diaria --sem-cobrancas`
- [ ] Só então deixar a cobrança automática ativa

Custo Parte 2: CoraPro ~R$ 44,90/mês fixo · Pix recebido sem tarifa por transação
(confirmar no contrato do CoraPro).

---

## Depois de ligar os dois

- [ ] Rodar `python manage.py rotina_diaria` manualmente uma vez e conferir o resultado
- [ ] Confirmar que o cron do Render (`cell-pag-rotina-diaria`, 08:30 BRT) rodou sem erro
- [ ] Acompanhar os primeiros dias: painel `/pagamentos/cobrar-hoje/`, `/pagamentos/pix/`,
      histórico em `/pagamentos/historico/`

Custo mensal com tudo ligado: Render ~US$ 15 + CoraPro ~R$ 45 + VPS Evolution ~R$ 30.

---

## Regras de segurança (não pular)

- [ ] Nenhum certificado, chave privada ou `.env` vai para o GitHub
- [ ] `EVOLUTION_WEBHOOK_TOKEN` e `CORA_WEBHOOK_TOKEN` são tokens fortes e diferentes
- [ ] Número do WhatsApp é um chip dedicado, não o pessoal da Yslane
- [ ] Testar sempre em Stage / `--somente-preparar` / `--sem-cobrancas` antes do envio real
