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
