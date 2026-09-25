# Hospedagem na VPS (KingHost + Coolify)

O site roda na mesma VPS da Evolution API, gerenciado pelo Coolify. Substitui o
Render (`docs/DEPLOY.md` e `render.yaml` ficam como alternativa). O código já vem
pronto: `Dockerfile`, `deploy/entrypoint.sh` e `.dockerignore`.

**Decisões**

- **Banco: PostgreSQL na própria VPS** (recurso do Coolify). O Neon fica nos EUA e
  cada consulta custaria ~130 ms de ida e volta; as telas fazem várias consultas,
  então ficariam lentas. Local, a latência é ~0.
- **Endereço:** um domínio `sslip.io` gerado pelo Coolify (HTTPS grátis) para
  começar. Domínio próprio é melhor a longo prazo: a URL do webhook da Cora e da
  Evolution ficam gravadas nesses serviços e trocar de domínio exige refazê-las.
- **Rotinas diárias:** Scheduled Tasks do Coolify (no lugar dos crons do Render).

## 1. Banco de dados

Coolify → projeto → **+ New** → **Database** → **PostgreSQL 16**.

1. Nome: `celulares-db`. Deixe **não** público (sem "Make it publicly available").
2. Copie a **Postgres URL (internal)**: é o `DATABASE_URL` do passo 3.
3. Em **Backups**, ative backup agendado diário. **Atenção:** backup só na mesma
   VPS não protege contra perder a VPS. Configure também um destino S3
   (Cloudflare R2 e Backblaze B2 têm plano grátis) assim que possível.

## 2. Aplicação

**+ New** → **Application** → **Public Repository**.

- Repositório: `https://github.com/mounjour/cell-pag`, branch `main`.
- **Build Pack: Dockerfile.** Porta exposta: `8000`.
- Em **Domains**: use **Generate Domain** (ou o seu domínio, com `https://`).
- **Persistent Storage:** volume em `/app/media` (comprovantes e documentos; sem
  ele os anexos somem a cada deploy).

## 3. Variáveis de ambiente (Coolify → Environment Variables)

| Variável | Valor |
|---|---|
| `SECRET_KEY` | texto aleatório longo (gerar como abaixo) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | o domínio exato, sem `https://` (ex.: `cell.191.252.212.198.sslip.io`) |
| `CSRF_TRUSTED_ORIGINS` | o domínio com `https://` |
| `DATABASE_URL` | Postgres URL (internal) do passo 1 |
| `WHATSAPP_PROVIDER` | `log` no início; `evolution` só depois de testar |
| `EVOLUTION_API_URL` | `https://evolution-celulares.vps-kinghost.net` |
| `EVOLUTION_API_KEY` | chave da Evolution |
| `EVOLUTION_INSTANCE` | `celulares` |
| `EVOLUTION_WEBHOOK_TOKEN` | texto aleatório longo |
| `YSLANE_WHATSAPP_NUMERO` | número da Yslane, ex.: `+5583988887777` |
| `WHATSAPP_PIX_CHAVE` | chave Pix de reserva (usada quando não há QR) |
| `CORA_PROVIDER` | `log` no início; `cora` depois |
| `CORA_CLIENT_ID` | client-id da Cora |
| `CORA_TOKEN_URL` | `https://matls-clients.api.cora.com.br/token` |
| `CORA_API_BASE_URL` | `https://matls-clients.api.cora.com.br` |
| `CORA_CERT_PATH` | `/tmp/cora/certificate.pem` |
| `CORA_KEY_PATH` | `/tmp/cora/private-key.key` |
| `CORA_CERT_B64` | certificado em base64 (abaixo) |
| `CORA_KEY_B64` | chave privada em base64 (abaixo) |
| `CORA_WEBHOOK_TOKEN` | texto aleatório longo |

Gerar um valor aleatório sem mostrá-lo na tela (PowerShell; cai na área de
transferência, e é só colar no Coolify):

```powershell
Set-Clipboard (-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 60 | ForEach-Object {[char]$_}))
```

Certificado e chave da Cora em base64, também direto para a área de
transferência (rode um, cole no `CORA_CERT_B64`; depois o outro, no `CORA_KEY_B64`):

```powershell
Set-Clipboard ([Convert]::ToBase64String([IO.File]::ReadAllBytes("secrets\cora\producao\certificate.pem")))
Set-Clipboard ([Convert]::ToBase64String([IO.File]::ReadAllBytes("secrets\cora\producao\private-key.key")))
```

O container recria os arquivos a partir dessas variáveis ao iniciar
(`deploy/entrypoint.sh`), com permissão `600`. Nada de segredo vai para a imagem
nem para o GitHub.

Marque `CORA_CERT_B64`, `CORA_KEY_B64`, `SECRET_KEY`, `DATABASE_URL` e as chaves
como **Runtime only** (não como "Build Variable").

## 4. Primeiro deploy

Clique em **Deploy**. O container aplica as migrações sozinho ao subir. Depois,
no terminal do container (Coolify → aplicação → **Terminal**) crie o primeiro
usuário:

```bash
python manage.py createsuperuser
```

## 5. Rotinas diárias (Scheduled Tasks)

Na aplicação → **Scheduled Tasks** → **+ Add**. O servidor está em **UTC**; os
horários abaixo já estão convertidos de Brasília (UTC−3):

| Nome | Comando | Frequência (cron) | Brasília |
|---|---|---|---|
| rotina-diaria | `python manage.py rotina_diaria` | `30 11 * * *` | 08:30 |
| retry-cobrancas-meio-dia | `python manage.py enviar_cobrancas_clientes` | `30 15 * * *` | 12:30 |
| retry-cobrancas-tarde | `python manage.py enviar_cobrancas_clientes` | `30 19 * * *` | 16:30 |

O retry é seguro: `processar_cobrancas` pula quem já foi enviado.

## 6. Webhooks

- **Evolution → site:** `https://SEU-DOMINIO/pagamentos/webhooks/whatsapp/`, evento
  `messages.update` (ver `docs/WHATSAPP.md`).
- **Cora → site:** `https://SEU-DOMINIO/pagamentos/webhooks/cora/` (ver
  `docs/CORA.md`). Sem o webhook o pagamento só é reconhecido pelo
  `reconciliar_cora`.

## 7. Ligar de verdade

Com o site no ar e testado (login, telas, um contrato de teste), troque
`CORA_PROVIDER=cora` e `WHATSAPP_PROVIDER=evolution` no Coolify e faça **Restart**.
Ligue um por vez, começando pelo WhatsApp.

## Atualizar o site

Push na `main` → no Coolify, **Deploy** (ou ative o webhook do GitHub para deploy
automático). As migrações rodam sozinhas.

## Observações de segurança

- Nunca coloque `.env`, certificados ou chaves no repositório (é público).
- Feche a porta `8000` do painel do Coolify no firewall quando o painel tiver
  domínio com HTTPS próprio.
- Guarde o `SECRET_KEY`: trocar invalida as sessões (todos precisam entrar de novo).
