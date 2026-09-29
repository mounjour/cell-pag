# Checklist de ativação — Cora (Pix) e Evolution API (WhatsApp)

> ✅ **Os dois já estão ligados de verdade em produção desde 28/09/2026**
> (`CORA_PROVIDER=cora`, `WHATSAPP_PROVIDER=evolution`). Este checklist fica
> como registro de como foi feito e referência para recriar um webhook ou
> emitir um certificado novo — não é mais um passo a passo pendente. A
> hospedagem é a VPS da KingHost com Coolify (ver
> [`DEPLOY-VPS.md`](../deploy/DEPLOY-VPS.md)), não mais o Render — os itens abaixo que
> citam Render/`cell-pag.onrender.com` são daquela época; o domínio atual é
> `celulares-pag.duckdns.org` e os *Secret Files* de certificado ficam nas
> variáveis de ambiente do Coolify, não em "Secret Files" do Render.
>
> Ordem recomendada: **1) Evolution → 2) Cora (Stage) → 3) Cora (produção)**.
> A cada `PROVIDER` trocado, rodar `manage.py rotina_diaria --sem-cobrancas` antes
> de deixar a cobrança automática ligada.

Python do venv (Windows): `.venv\Scripts\python.exe`

---

## Parte 1 — Evolution API (WhatsApp)

Software open-source e gratuito. Não se compra a API — hospeda-se. Custo = servidor.

### Contratar / hospedar
- [x] Contratar um VPS pequeno (~R$ 20–40/mês: Hetzner, Contabo, DigitalOcean, Railway, Fly.io)
- [x] Apontar um subdomínio com HTTPS (ex.: `evolution.sualoja.com.br`)
- [x] Subir a Evolution API via Docker (imagem `evoapicloud/evolution-api`)
- [x] Definir a API Key global da Evolution
- [x] Separar um chip / número de WhatsApp DEDICADO (não usar o pessoal da Yslane)
- [x] Criar uma instância na Evolution e conectar o número lendo o QR Code

### Configurar no projeto
- [x] Preencher no `.env` (local) ou nas variáveis de ambiente do Coolify:
  - [x] `WHATSAPP_PROVIDER=evolution`
  - [x] `EVOLUTION_API_URL=https://evolution.sualoja.com.br`
  - [x] `EVOLUTION_API_KEY=` (a chave)
  - [x] `EVOLUTION_INSTANCE=` (nome da instância)
  - [x] `EVOLUTION_WEBHOOK_TOKEN=` (token aleatório forte)
  - [x] `WHATSAPP_PIX_CHAVE=` (chave Pix que aparece no texto da cobrança)
  - [x] `YSLANE_WHATSAPP_NUMERO=+5583XXXXXXXXX` (E.164 — para o lembrete diário)
- [x] Cadastrar na Evolution o webhook do evento `messages.update` apontando para:
      `https://celulares-pag.duckdns.org/pagamentos/webhooks/whatsapp/`
- [x] Autenticar esse webhook com o mesmo `EVOLUTION_WEBHOOK_TOKEN` (header `apikey`)

### Testar
- [x] `python manage.py enviar_cobrancas_clientes --somente-preparar` (monta a fila, não envia)
- [x] `python manage.py rotina_diaria --sem-cobrancas` (confere que nada quebrou)
- [x] `python manage.py enviar_cobrancas_clientes` (envia de verdade — testar com 1 contrato)
- [x] Conferir no painel `/pagamentos/` que os status mudam para enviado / entregue / lido

Custo Parte 1: VPS ~R$ 20–40/mês · software grátis · chip pré-pago.

---

## Parte 2 — Cora (Pix automático)

A API ("Integração Direta") não é aberta. Exige o plano CoraPro + certificado mTLS.

### Contratar
- [x] Abrir conta PJ na Cora (com o CNPJ da loja) — grátis
- [x] Assinar o plano **CoraPro** (~R$ 44,90/mês) no app ou Cora Web
- [x] Solicitar acesso de **Integração Direta**
- [x] Emitir o certificado mTLS do ambiente **Stage** (homologação): arquivos `.PEM` + `.KEY`
- [x] Guardar `certificate.pem` e `private-key.key` FORA do repositório (nunca no GitHub)

### Configurar no projeto — Stage primeiro
- [x] Preencher no `.env` / variáveis de ambiente do Coolify:
  - [x] `CORA_PROVIDER=cora`
  - [x] `CORA_CLIENT_ID=` (client id da Cora)
  - [x] `CORA_CERT_PATH=` (caminho do `.pem`)
  - [x] `CORA_KEY_PATH=` (caminho do `.key`)
  - [x] `CORA_TOKEN_URL=https://matls-clients.api.stage.cora.com.br/token`
  - [x] `CORA_API_BASE_URL=https://matls-clients.api.stage.cora.com.br`
  - [x] `CORA_WEBHOOK_TOKEN=` (token aleatório forte)
- [x] Cadastrar o webhook na Cora:
      `https://celulares-pag.duckdns.org/pagamentos/webhooks/cora/?token=<CORA_WEBHOOK_TOKEN>`
  - [x] Recurso: `invoice`
  - [x] Gatilhos: `paid`, `overdue`, `canceled`

### Na produção (Coolify)
- [x] Certificado/chave da Cora entram como variável de ambiente no Coolify
      (não como "Secret Files" — isso era do Render)
- [x] `CORA_CERT_PATH` / `CORA_KEY_PATH` apontam para onde o Coolify grava
      essas variáveis no container

### Testar no Stage
- [x] `python manage.py criar_cobranca_teste` (cria e consulta uma cobrança de ponta a ponta)
- [x] `python manage.py reconciliar_cora` (confere Pix abertos)
- [x] `python manage.py rotina_diaria --sem-cobrancas` (confere que nada quebrou)
- [x] Conferir a tela `/pagamentos/pix/` (pagos / aguardando / não pagos / erros)

### Migrar para produção
- [x] Emitir o certificado mTLS de **produção** na Cora (par separado do Stage)
- [x] Trocar `CORA_TOKEN_URL` e `CORA_API_BASE_URL` para as URLs de produção
- [x] Trocar as variáveis de ambiente pelos certificados de produção
- [x] Recadastrar o webhook no ambiente de produção da Cora
- [x] Repetir `criar_cobranca_teste` + `rotina_diaria --sem-cobrancas`
- [x] Só então deixar a cobrança automática ativa

Custo Parte 2: CoraPro ~R$ 44,90/mês fixo · Pix recebido sem tarifa por transação
(confirmar no contrato do CoraPro).

---

## Depois de ligar os dois

- [x] Rodar `python manage.py rotina_diaria` manualmente uma vez e conferir o resultado
- [x] Confirmar que a Scheduled Task do Coolify (`rotina_diaria`, 08:30 BRT) rodou sem erro
- [x] Acompanhar os primeiros dias: painel `/pagamentos/cobrar-hoje/`, `/pagamentos/pix/`,
      histórico em `/pagamentos/historico/`

Custo mensal real: VPS única da KingHost (site + Evolution) + CoraPro ~R$ 45 (confirmar valor atual no contrato). Estimativa de Render/VPS separada acima é da época em que o plano ainda era hospedar cada peça à parte.

---

## Regras de segurança (não pular)

- [x] Nenhum certificado, chave privada ou `.env` vai para o GitHub
- [x] `EVOLUTION_WEBHOOK_TOKEN` e `CORA_WEBHOOK_TOKEN` são tokens fortes e diferentes
- [x] Número do WhatsApp é um chip dedicado, não o pessoal da Yslane
- [x] Testar sempre em Stage / `--somente-preparar` / `--sem-cobrancas` antes do envio real
