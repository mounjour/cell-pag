# Sistema de Acompanhamento de Pagamentos de Celulares

Controle dos pagamentos de aparelhos vendidos a prazo (estruturas diária, semanal, por
dezena, quinzenal e mensal). Uso principal do financeiro, com acesso do dono para
relatórios e acordos.

Contexto completo do projeto: `PLANO-DO-PROJETO.md` (não versionado).

## Requisitos

- Python 3.12+ (testado com 3.14)
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

Acesse `http://127.0.0.1:8000/` — a raiz leva à lista de clientes (exige login em `/entrar/`).

## Testes

```bash
pytest
```

## Estrutura

```
config/            configuração do projeto (settings, urls, wsgi/asgi)
apps/
  usuarios/        usuário customizado (perfil: financeiro | dono) + login/logout
  clientes/        cadastro de clientes — CRUD web + admin com import/export
  contratos/       contratos/aparelhos + documentos anexos — CRUD web
  pagamentos/      vencimentos, baixas, atraso e agenda diária
  relatorios/      consolidação diária/semanal/mensal + Excel/PDF
templates/         templates de projeto
static/            arquivos estáticos de projeto
```

## Estado atual

Fases 1 a 6 implementadas: cadastros, geração de vencimentos nas cinco estruturas,
agenda "Cobrar hoje", baixa manual (inclusive parcial), atraso/juros/status e
relatórios para o perfil dono. Os relatórios aceitam período diário, semanal,
mensal ou personalizado e exportam os mesmos dados em Excel e PDF.

A Fase 6 prepara diariamente uma cobrança por contrato e envia mensagens-template
pela API oficial do WhatsApp, com webhook para os estados enviado, entregue, lido
e erro. Por segurança, o padrão é `WHATSAPP_PROVIDER=log`: a fila é criada, mas
nada sai do sistema. Depois de configurar a conta Meta e aprovar os três templates,
troque para `WHATSAPP_PROVIDER=meta` e agende:

```bash
python manage.py enviar_cobrancas_clientes
```

O endpoint a cadastrar na Meta é `/pagamentos/webhooks/whatsapp/`.
Veja os templates, parâmetros e passos de ativação em `docs/WHATSAPP.md`.

Depois de atualizar o projeto, aplique a migração que registra a data real de
quitação dos contratos:

```bash
python manage.py migrate
```

## Comandos úteis

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py check
```
