# Pix automático com a Cora - Fase 7

O fluxo implementado cria um QR Code Pix por parcela, envia o código pelo fluxo
oficial do WhatsApp, consulta o estado da fatura e registra a baixa automática
somente depois que a API autenticada da Cora confirma o pagamento.

## Modo seguro

O padrão é:

```env
CORA_PROVIDER=log
```

Nesse modo são criados registros locais com estado "Aguardando geração", sem
chamar a Cora e sem movimentar dinheiro. Para ativar a integração, solicite no
aplicativo ou Cora Web as credenciais de Integração Direta do ambiente Stage.

## Configuração de Stage

Guarde o certificado e a chave fora do repositório e preencha o `.env`:

```env
CORA_PROVIDER=cora
CORA_CLIENT_ID=
CORA_CERT_PATH=C:\caminho-seguro\certificate.pem
CORA_KEY_PATH=C:\caminho-seguro\private-key.key
CORA_TOKEN_URL=https://matls-clients.api.stage.cora.com.br/token
CORA_API_BASE_URL=https://matls-clients.api.stage.cora.com.br
```

Nunca envie o certificado, a chave privada ou o `.env` ao GitHub.

## Rotina

Depois de gerar os vencimentos, execute:

```bash
python manage.py gerar_vencimentos
python manage.py enviar_cobrancas_clientes
```

O segundo comando primeiro reconcilia cobranças conhecidas, depois cria o Pix
que falta e prepara/envia a mensagem do dia. Uma chamada adicional pode rodar
periodicamente:

```bash
python manage.py reconciliar_cora
```

## Webhook

Cadastre na Cora:

```text
https://SEU-DOMINIO/pagamentos/webhooks/cora/
```

Recursos: `invoice`; gatilhos: `paid`, `overdue` e `canceled`.

Como a documentação pública da Cora descreve os identificadores em cabeçalhos,
mas não uma assinatura criptográfica da notificação, o webhook não consulta a
API nem dá baixa diretamente. Ele apenas registra um sinal para uma fatura já
conhecida. A rotina interna consulta a Cora com certificado mTLS e só então
atualiza o sistema.

## Regras aplicadas

- Uma cobrança Pix por parcela, protegida por UUID de idempotência.
- O valor do QR é o principal da parcela; os juros continuam informados fora do
  QR, conforme a decisão do projeto.
- Se uma cobrança atrasada precisar ser criada após o vencimento, a API recebe
  o dia atual porque a Cora não aceita uma nova fatura com data passada. A data
  original da parcela permanece registrada no sistema.
- `PAID` cria uma baixa automática com usuário vazio e observação contendo o ID
  Cora; pagamentos já lançados manualmente não são duplicados.
- A tela `/pagamentos/pix/` mostra pagos, aguardando, não pagos e erros.

Documentação oficial:

- https://developers.cora.com.br/docs/client-credentials-int-direta
- https://developers.cora.com.br/reference/qr-code-pix-v2
- https://developers.cora.com.br/reference/consultar-detalhes-de-um-boleto-v2
- https://developers.cora.com.br/reference/exemplo-de-post-da-notifica%C3%A7%C3%A3o
