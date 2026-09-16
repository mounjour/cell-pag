# WhatsApp via Evolution API — ativação da Fase 6

O sistema envia as cobranças e o lembrete diário pela **Evolution API** (uma
API não-oficial de WhatsApp, self-hosted). Substitui a WhatsApp Cloud API da
Meta — não há mais templates aprovados: a mensagem montada em
`apps/pagamentos/cobranca.py` vai inteira como texto livre.

Enquanto não houver uma instância da Evolution conectada, mantenha:

```env
WHATSAPP_PROVIDER=log
```

Nesse modo o job cria a fila e mostra "Pendente" no painel, mas nada é enviado.
Nenhum cliente é contatado por engano.

## Subindo a Evolution API (VPS + Coolify)

A Evolution é self-hosted — não roda no Render (ver `docs/DEPLOY.md`). O
caminho mais simples para não virar trabalho manual de servidor é: uma VPS
qualquer + **Coolify** (painel self-hosted que cuida de HTTPS, reinício
automático e deploy) + bancos **externos gerenciados** (para a VPS não guardar
nenhum estado importante).

### 1. Provisionar a VPS

Qualquer provedor serve (DigitalOcean, Hetzner, Contabo, Vultr...). Plano
pequeno (1-2GB RAM) é suficiente. Anote o IP e aponte um subdomínio para ele
(ex.: `evolution.seudominio.com`), via registro DNS tipo A.

### 2. Instalar o Coolify

Via SSH na VPS:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Ao final, o instalador mostra a URL do painel (`http://SEU-IP:8000`). Acesse,
crie o usuário admin, e cadastre o domínio (`evolution.seudominio.com`) nas
configurações do servidor — o Coolify emite o certificado HTTPS sozinho
(Let's Encrypt).

### 3. Criar os bancos externos (a VPS não guarda estado)

- **Postgres da Evolution:** crie um **segundo projeto no Supabase** (separado
  do banco do sistema Django) só para a Evolution. Copie a connection string.
- **Redis:** use um serviço gerenciado com plano grátis (ex.: Upstash). Copie
  a URL de conexão (`rediss://...`).

Isso importa porque, se a VPS tiver problema, dá pra recriar o servidor do
zero sem perder sessão do WhatsApp nem histórico de mensagens — só reconecta
o container nos mesmos bancos.

### 4. Subir a Evolution API pelo Coolify

No painel do Coolify: **New Resource → Docker Compose** (ou o template pronto
de Evolution API, se o Coolify oferecer um). Aponte:

- `DATABASE_CONNECTION_URI` → a connection string do Postgres (Supabase)
- `CACHE_REDIS_URI` → a URL do Redis (Upstash)
- Domínio → `evolution.seudominio.com` (HTTPS automático pelo Coolify)

Publique. O Coolify cuida do reinício automático se o container cair ou o
servidor reiniciar.

### 5. Criar a instância e conectar o número

Acesse `https://evolution.seudominio.com/manager` (painel web da própria
Evolution, não o Coolify):

1. Crie uma instância (dê um nome, ex.: `celulares-cobranca`) — esse nome é o
   `EVOLUTION_INSTANCE`.
2. Escaneie o QR Code exibido com o WhatsApp do número que vai enviar as
   cobranças.
3. Pegue a **API Key** gerada — esse valor é o `EVOLUTION_API_KEY`.

### 6. Monitoramento básico

Cadastre `https://evolution.seudominio.com` num serviço de uptime check
gratuito (ex.: UptimeRobot) para avisar por e-mail se a instância cair.

## Credenciais

Com a instância no ar (passo anterior), preencha o `.env`:

```env
WHATSAPP_PROVIDER=evolution
EVOLUTION_API_URL=https://sua-evolution.exemplo.com
EVOLUTION_API_KEY=chave-global-ou-da-instancia
EVOLUTION_INSTANCE=nome-da-instancia
EVOLUTION_WEBHOOK_TOKEN=um-token-aleatorio-forte
```

O envio usa `POST {EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}`
com o cabeçalho `apikey` e corpo `{"number": "...", "text": "..."}`.

## QR code Pix (imagem)

Depois do texto (que já leva o copia-e-cola embutido na mensagem), o sistema
também envia o **PNG do QR code** gerado pela Cora (`CobrancaCora.qr_code_url`)
como uma segunda mensagem, via
`POST {EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}`.

Esse endpoint da Evolution só aceita o arquivo em `multipart/form-data`
(binário) — não aceita URL no corpo. Por isso [`enviar_imagem()`](../apps/pagamentos/whatsapp.py)
baixa o PNG da Cora e repassa os bytes.

O envio da imagem é "melhor esforço": se falhar, fica só um aviso no log —
não muda o status da `Cobranca` nem conta como erro dela, porque o cliente já
recebeu o copia-e-cola por texto e consegue pagar mesmo sem a imagem.

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

- https://docs.evolutionfoundation.com.br/
- https://coolify.io/docs/
