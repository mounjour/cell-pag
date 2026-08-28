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
  pagamentos/      registro de pagamentos e cobrança  [esqueleto — Fase 2+]
templates/         templates de projeto
static/            arquivos estáticos de projeto
```

## Estado atual

Fase 1 (Cadastros): clientes e contratos com telas próprias fora do admin, login por
usuário, anexo de documentos ao contrato. A geração de vencimentos e o cálculo da
parcela (Fase 2) dependem de regras ainda em aberto — ver `PLANO-DO-PROJETO.md`,
seção 10.

## Comandos úteis

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py check
```
