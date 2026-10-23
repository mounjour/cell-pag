# Sistema de Acompanhamento de Pagamentos de Celulares

Controle dos pagamentos de aparelhos vendidos ou alugados a prazo (parcelas semanais,
quinzenais e mensais). Uso diário do financeiro (Yslane) e do dono (Alisson): cobrança
automática por WhatsApp, Pix com conferência pelo extrato da Cora, baixa de pagamentos,
bloqueio de aparelhos, relatórios e um conector para registrar tudo pelo Claude Desktop.

Contexto completo do projeto: `PLANO-DO-PROJETO.md` (não versionado). Documentação de uso,
deploy, integrações e segurança: [`docs/`](docs/README.md).

## O que o sistema faz

- **Clientes, contratos e aparelhos:** cadastro, importação por planilha, geração automática
  das parcelas (`Vencimento`) ao salvar o contrato, estoque e catálogo de aparelhos.
- **Cobrança:** painel "Cobrar hoje", próximas cobranças, promessas de pagamento, contatos
  registrados e acordos (renegociação). Atraso com juros diários por contrato, **sem multa**;
  alerta de bloqueio no 8º dia de atraso.
- **Pagamentos:** baixa manual (inclusive parcial, com troco e juros separados), edição e
  estorno, histórico por cliente/contrato.
- **WhatsApp (Evolution API):** envio das cobranças e confirmações, com webhook de estados
  (enviado, entregue, lido, erro) e retentativas ao longo do dia.
- **Pix e Cora:** modo `estatico` (código copia e cola montado no sistema) ou `fatura`
  (fatura Pix criada na Cora). Os pagamentos entram pela leitura do extrato ("Pix recebidos"),
  com baixa automática quando o CPF e o valor batem, e a "Conferência com a Cora" aponta
  divergências.
- **Bloqueios:** lista de aparelhos a bloquear/desbloquear, com o registro de quem fez.
- **Relatórios:** início, painel e juros, por período, com exportação em Excel e PDF.
- **Saúde das rotinas:** mostra se as rotinas agendadas rodaram e qual versão está publicada.
- **Claude Desktop:** conector (MCP) para consultar atrasos e contratos e registrar
  pagamentos, contatos e bloqueios por conversa. Cada pessoa tem a sua chave, o Claude Desktop
  pede permissão antes de gravar e a tela lista tudo o que foi gravado (com "Desfazer").

## Requisitos

- Python 3.12+ (produção usa 3.12; o CI roda em 3.12 e 3.13)
- SQLite no desenvolvimento; PostgreSQL em produção

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # Linux/Mac
pip install -r requirements-dev.txt   # runtime + ferramentas de teste
copy .env.example .env            # cp .env.example .env  (Linux/Mac) — depois ajuste
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse `http://127.0.0.1:8000/`: a raiz abre a tela inicial dos relatórios (exige login em `/entrar/`).

## Testes

```bash
pytest
```

O CI (GitHub Actions) roda o `pytest` e uma varredura de segredos (gitleaks) em todo PR.

## Estrutura

```
config/            configuração do projeto (settings, urls, wsgi/asgi)
apps/
  usuarios/        usuário customizado (perfil: financeiro | dono), login e termos
  clientes/        cadastro de clientes, situação (em dia/atrasado) e importação
  aparelhos/       estoque, catálogo e bloqueios de aparelhos
  contratos/       contratos, documentos anexos, importação e pendências
  pagamentos/      parcelas, baixas, atraso/juros, cobrança, WhatsApp, Pix/Cora, rotinas
  relatorios/      início, painel e juros, com Excel/PDF
  assistente/      conector do Claude Desktop (API por chave, ferramentas, instalador)
templates/         templates de projeto
static/            CSS, JS e imagens
docs/              uso, deploy, integrações e segurança
deploy/            entrypoint do contêiner
```

## Configuração

Tudo vem de variáveis de ambiente (veja `.env.example`). As integrações têm padrões seguros:

| Variável | Padrão | Para quê |
|---|---|---|
| `WHATSAPP_PROVIDER` | `log` | `log` só cria a fila; `evolution` envia de verdade |
| `CORA_PROVIDER` | `log` | `log` não fala com a Cora; use a configuração de Stage antes da produção |
| `PIX_MODO` | `fatura` | `estatico` monta o Pix no sistema (usado em produção) |
| `EVOLUTION_*` | vazio | URL, chave, instância e token do webhook da Evolution |
| `CORA_*` | vazio | credenciais, certificado e token do webhook da Cora |

Chaves e certificados ficam só no ambiente de produção (Coolify) e nunca no repositório.
Os passos de ativação estão em `docs/integracoes/` (`WHATSAPP.md`, `CORA.md`).

## Rotinas agendadas

```bash
python manage.py rotina_diaria            # gera vencimentos, lembrete diário e cobranças
python manage.py enviar_cobrancas_clientes # envia as cobranças do dia (roda de novo mais tarde como retentativa)
python manage.py conferir_recebidos       # lê o extrato da Cora e baixa os Pix reconhecidos
python manage.py reconciliar_cora         # confere as cobranças Pix abertas na Cora e registra baixas confirmadas
```

Em produção rodam como Scheduled Tasks do Coolify (servidor em UTC); horários e comandos em
`docs/deploy/DEPLOY-VPS.md`. A tela **Saúde das rotinas** mostra se cada uma rodou.

## Deploy

Produção roda numa VPS com **Coolify**, a partir do `Dockerfile` (o `deploy/entrypoint.sh`
aplica as migrações na subida). Todo merge na `main` publica automaticamente pelo webhook do
GitHub. Detalhes em `docs/deploy/DEPLOY-VPS.md`; o Render (`render.yaml`) ficou como alternativa antiga.

## Claude Desktop

Cada pessoa abre **Claude Desktop** no menu do sistema, cria a chave, baixa o instalador
(`.cmd`, Windows, precisa de Python) e segue o passo a passo da tela. O instalador baixa o
conector, ajusta a configuração do Claude Desktop e testa a ligação. As instruções para o
Projeto/conversa do Claude saem de `apps/assistente/conector/instrucoes.md`. A API fica em
`/assistente/api/` e só aceita a chave (guardada apenas como hash).

## Comandos úteis

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py check
python manage.py rotina_diaria --hoje 2026-10-01 --sem-cobrancas
```
