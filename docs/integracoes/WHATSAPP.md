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

## Comprovantes e confirmação de pagamento

Para o sistema saber que o cliente mandou um comprovante, o mesmo webhook precisa
receber também o evento **`messages.upsert`** (mensagens recebidas). Na Evolution,
inclua `MESSAGES_UPSERT` nos eventos do webhook (além de `MESSAGES_UPDATE`) e
deixe **desligado** o envio da mídia em base64 (`webhook_base64: false`): o sistema
não guarda a imagem e uma mídia grande no aviso só atrapalha.

O que acontece quando um cliente cadastrado manda uma **imagem ou PDF**:

1. O sistema reconhece o cliente pelo número e a parcela em aberto mais antiga.
   Texto, áudio, figurinhas, grupos e números que não são de cliente são ignorados.
2. Consulta a Cora. Se o Pix já foi pago, dá a baixa e confirma ao cliente.
3. Se ainda não caiu, responde ao cliente ("recebemos o comprovante, ainda não
   identificamos o Pix; avisamos quando cair", no máximo uma vez a cada 6 horas) e
   mostra o alerta no painel **Pix** (com selo no menu). O financeiro pode abrir o
   WhatsApp, conferir na Cora ou descartar se não for comprovante.

**A imagem nunca conta como pagamento** — só a Cora confirma. O arquivo não é
guardado, apenas o aviso de que chegou (quem, quando, tipo, legenda).

**Confirmação:** todo Pix confirmado pela Cora gera, junto com a baixa automática,
uma mensagem "Recebemos o seu pagamento de R$ X (parcela N)" ao cliente, uma única
vez. Em `WHATSAPP_PROVIDER=log` nada é enviado.

**Pagamento em dinheiro depois da cobrança:** ao registrar a baixa manual, o Pix em
aberto é cancelado e a mensagem de cobrança já enviada é apagada do WhatsApp do
cliente (`WHATSAPP_APAGAR_AO_BAIXAR`, dentro de `WHATSAPP_APAGAR_JANELA_HORAS`
horas — o limite do próprio WhatsApp). Se não for possível, a tela avisa. Se o
cliente pagar o Pix também, o painel Pix mostra a duplicidade para devolução.

## Grupo do cliente com a equipe

Em vez do telefone do cliente, as mensagens do sistema podem ir para um **grupo do WhatsApp** em que ele
está junto com o financeiro (assim a equipe acompanha tudo no mesmo lugar).

- **Cadastro:** em **Editar cliente**, o campo *Grupo do WhatsApp* lista os grupos do número da empresa
  (nome e quantidade de participantes). Sem lista (Evolution fora do ar), dá para colar o identificador
  (termina em `@g.us`). Sem grupo escolhido, tudo continua indo para o telefone do cliente.
- **O que vai para o grupo:** a cobrança (mensagem e Pix), a confirmação de pagamento e o aviso de
  comprovante. A mensagem apagada ao dar baixa também é apagada no grupo.
- **Comprovante no grupo:** o sistema só lê imagem ou PDF mandado **pelo próprio cliente** no grupo
  cadastrado (confere o número de quem enviou). Mensagens do financeiro, de outras pessoas ou de grupos
  desconhecidos são ignoradas.
- **Na Evolution:** o número da empresa precisa estar no grupo; o evento `MESSAGES_UPSERT` do webhook
  continua ligado e a configuração **Ignorar grupos (`groupsIgnore`) deve ficar DESLIGADA**, senão a
  Evolution descarta o que chega dos grupos.
- **Cuidado:** a cobrança mostra valores e juros para **todos** do grupo. Use só grupos com o cliente e a
  equipe.

## Quando a conexão cai ("Connection Closed")

A Evolution às vezes fica com o estado **"Conectado"** mesmo com a conexão real morta (o estado é só uma
variável dela). Os envios passam a falhar com `Connection Closed`.

- **Recuperação automática:** se um envio da rotina falhar assim, o sistema reinicia a conexão
  (`POST /instance/restart/{instância}`, sem perder a sessão e sem QR), espera uns segundos e tenta de novo.
  Só reinicia **uma vez por rotina**. A rotina registra o aviso e, se ainda houver erro, a falha mostra
  quantas cobranças ficaram com erro.
- **Botão manual:** em **Conexões**, **Reiniciar a conexão** faz o mesmo. Se a Evolution já sabe que está
  desconectada (`close`), o sistema pede a reconexão (`GET /instance/connect/{instância}`). **Desconectar e ler o
  QR de novo** (logout) é o último recurso: o logout falha com a conexão morta, por isso não é o primeiro passo.
- **Aviso:** cobranças de hoje com erro aparecem nas notificações (sino) e como aviso na tela **Mensagens**.
- **Causa de queda que já tivemos:** o banco da Evolution no Neon (hiberna e fica inacessível justo na hora de
  reconectar; erro `P1001` nos logs). Hoje o banco da Evolution é um PostgreSQL na própria VPS, no compose
  da Evolution, sem esse problema.

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
