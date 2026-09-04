# WhatsApp oficial - ativação da Fase 6

O sistema usa mensagens-template da WhatsApp Cloud API. Enquanto a conta Meta,
o número comercial e os templates não estiverem prontos, mantenha:

```env
WHATSAPP_PROVIDER=log
```

Nesse modo, o job cria a fila e exibe o estado "Pendente" no painel, mas não
envia mensagens. Nenhum cliente é contatado por engano.

## Credenciais

Preencha no `.env`:

```env
WHATSAPP_PROVIDER=meta
WHATSAPP_GRAPH_VERSION=vXX.X
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_WEBHOOK_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_PIX_CHAVE=
```

Use em `WHATSAPP_GRAPH_VERSION` uma versão atualmente suportada pela Meta. Ela
não fica fixa no código para evitar que o envio pare quando uma versão expirar.

## Templates

Cadastre e aprove três templates em português do Brasil (`pt_BR`). A ordem das
variáveis precisa ser exatamente esta:

### `cobranca_vencimento`

1. Nome do cliente
2. Data do vencimento
3. Número da parcela
4. Aparelho
5. Valor
6. Chave Pix

Texto sugerido:

> Oi, {{1}}! Hoje ({{2}}) vence a parcela {{3}} do seu {{4}}, no valor de R$ {{5}}. Você pode pagar via Pix ({{6}}) e enviar o comprovante por aqui.

### `cobranca_atraso`

1. Nome do cliente
2. Número da parcela
3. Aparelho
4. Data do vencimento
5. Dias de atraso
6. Valor atualizado
7. Chave Pix

Texto sugerido:

> Oi, {{1}}! A parcela {{2}} do seu {{3}}, vencida em {{4}}, está em aberto há {{5}} dia(s). O valor atualizado é R$ {{6}}. Faça o Pix para {{7}} e envie o comprovante. Se já pagou, desconsidere.

### `cobranca_bloqueio`

1. Nome do cliente
2. Número da parcela
3. Aparelho
4. Dias de atraso
5. Valor atualizado
6. Chave Pix

Texto sugerido:

> Oi, {{1}}! A parcela {{2}} do seu {{3}} está com {{4}} dias de atraso. Regularize hoje para evitar o bloqueio do aparelho. Valor atualizado: R$ {{5}} - Pix {{6}}. Fale conosco se precisar de ajuda.

Se os nomes aprovados forem diferentes, altere as variáveis
`WHATSAPP_TEMPLATE_VENCIMENTO`, `WHATSAPP_TEMPLATE_ATRASO` e
`WHATSAPP_TEMPLATE_BLOQUEIO`.

## Webhook

Cadastre na Meta a URL pública HTTPS:

```text
https://SEU-DOMINIO/pagamentos/webhooks/whatsapp/
```

Use o mesmo valor de `WHATSAPP_WEBHOOK_VERIFY_TOKEN` na Meta. O sistema valida
as notificações recebidas com `WHATSAPP_APP_SECRET` e atualiza os estados:
enviado, entregue, lido ou erro.

## Rotina diária

Depois de gerar os vencimentos, execute:

```bash
python manage.py gerar_vencimentos
python manage.py enviar_cobrancas_clientes
```

Para conferir a fila sem chamar a Meta:

```bash
python manage.py enviar_cobrancas_clientes --somente-preparar
```

O job é idempotente: só existe uma cobrança por contrato, dia e canal. Contratos
atrasados voltam à fila a cada novo dia até o pagamento ser registrado.

Documentação técnica da Meta:

- https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
- https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference
