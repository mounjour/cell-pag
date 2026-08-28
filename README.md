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
pip install -r requirements.txt
copy .env.example .env            # cp .env.example .env  (Linux/Mac) — depois ajuste
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse `http://127.0.0.1:8000/` — a raiz redireciona para o admin em `/admin/`.

## Estrutura

```
config/            configuração do projeto (settings, urls, wsgi/asgi)
apps/
  usuarios/        modelo de usuário customizado (perfil: financeiro | dono)
  clientes/        cadastro de clientes  [implementado]
  contratos/       contratos, aparelhos e vencimentos  [aguardando Fase 0]
  pagamentos/      registro de pagamentos e cobrança   [aguardando Fase 0]
templates/         templates de projeto
static/            arquivos estáticos de projeto
```

## Estado atual

Criação inicial concluída: projeto Django, apps, usuário customizado, cadastro de
`Cliente` e admin. Os apps `contratos` e `pagamentos` estão como esqueleto — dependem de
regras de negócio ainda em aberto (`PLANO-DO-PROJETO.md`, seção 10).

## Comandos úteis

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py check
```
