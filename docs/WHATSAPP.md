# WhatsApp via Evolution API — ativação da Fase 6

O sistema envia as cobranças e o lembrete diário pela **Evolution API** (uma
API não-oficial de WhatsApp, self-hosted). Substitui a WhatsApp Cloud API da
Meta — não há mais templates aprovados: a mensagem montada em
`apps/pagamentos/cobranca.py` vai inteira como texto livre.

Provedor de VPS escolhido para hospedar a Evolution: **KingHost** (VPS Ubuntu
24.04 LTS com Docker, 4 GB de RAM, 2 vCPU), com o **Coolify** por cima (HTTPS
automático e deploy por painel). Banco Postgres da Evolution: **Neon** (conexão
direta, sem pooling). Redis local, no mesmo compose.

## Como está no ar (produção)

- Endereço: `https://evolution-celulares.vps-kinghost.net` (manager em `/manager`).
- Imagem: `evoapicloud/evolution-api:v2.3.7`. A `atendai/evolution-api` foi
  descontinuada no Docker Hub e o download é recusado.
- Subida: recurso **Docker Compose** no Coolify, com `evolution` (porta interna
  8080) e `redis`. O domínio se cadastra em **Domains** do serviço (protocolo
  `https`, domínio sem `https://` e sem porta, campo **Port** = `8080`); depois
  de salvar, **Restart** para o Traefik receber as etiquetas.
- Variáveis (Coolify → Environment Variables): `EVOLUTION_API_KEY`,
  `DATABASE_CONNECTION_URI` (Neon, `?sslmode=require&connection_limit=15&pool_timeout=30`)
  e `DATABASE_SAVE_IS_ON_WHATSAPP=false`. Sem o pool maior e sem esta última, a
  sincronização inicial dos contatos estoura o limite de conexões com o Neon.
- Instância `celulares` (`WHATSAPP-BAILEYS`), criada por
  `POST /instance/create` e conectada pelo QR no manager. Após um Restart ela
  reconecta sozinha. O "Bad Gateway" logo após o Restart é só a demora de subir.
- Números sempre com o código do país: `5588...`. Sem o `55` a Evolution
  responde 400 (`exists: false`).

Enquanto não houver uma instância da Evolution conectada, mantenha:

```env
WHATSAPP_PROVIDER=log
```

Nesse modo o job cria a fila e mostra "Pendente" no painel, mas nada é enviado.
Nenhum cliente é contatado por engano.

## Credenciais

Suba uma instância da Evolution API (Docker) e conecte um número lendo o QR
Code. Depois preencha o `.env`:

```env
WHATSAPP_PROVIDER=evolution
EVOLUTION_API_URL=https://sua-evolution.exemplo.com
EVOLUTION_API_KEY=chave-global-ou-da-instancia
EVOLUTION_INSTANCE=nome-da-instancia
EVOLUTION_WEBHOOK_TOKEN=um-token-aleatorio-forte
```

O envio usa `POST {EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}`
com o cabeçalho `apikey` e corpo `{"number": "...", "text": "..."}`.

Quando a cobrança já tem um QR code Pix gerado pela Cora (`CORA_PROVIDER=cora`),
o envio troca para `POST {EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}`
(`{"number": "...", "mediatype": "image", "media": "<qr_code_url>", "caption":
"<mesma mensagem>", "fileName": "qrcode-pix.png"}`) — o cliente recebe a imagem
do QR code com a mensagem de cobrança como legenda, em vez de só o texto com o
código "copia e cola". Sem QR real (`CORA_PROVIDER=log`), continua indo só o
texto.

## Webhook de status

Configure na Evolution o webhook para o evento `messages.update` apontando para
a URL pública HTTPS:

```text
https://SEU-DOMINIO/pagamentos/webhooks/whatsapp/
```

Como a Evolution **não assina** os eventos, a autenticação é por token
compartilhado: o mesmo valor de `EVOLUTION_WEBHOOK_TOKEN` deve chegar no
cabeçalho `apikey` (ou `Authorization: Bearer ...`, ou `?token=`). Sem token
configurado, o endpoint só responde com `DEBUG=True`.

Os ACKs da Evolution (texto `SERVER_ACK`/`DELIVERY_ACK`/`READ`/`PLAYED`, ou os
números `1..4`) viram os estados: enviado, entregue e lido. `ERROR` marca erro.
O webhook nunca regride um estado já alcançado.

## Rotina diária

Depois de gerar os vencimentos, execute:

```bash
python manage.py gerar_vencimentos
python manage.py enviar_cobrancas_clientes
```

Para conferir a fila sem chamar a Evolution:

```bash
python manage.py enviar_cobrancas_clientes --somente-preparar
```

O job é idempotente: só existe uma cobrança por contrato, dia e canal.
Contratos atrasados voltam à fila a cada novo dia até o pagamento ser
registrado.

Documentação da Evolution API:

- https://doc.evolution-api.com/
