"""Popula o banco com dados de demonstração: 10 clientes e 10 contratos.

Serve de ponto de partida para o protótipo (quem for usar já abre o sistema
com dados dentro) e de massa para testes manuais. Cobre as 5 estruturas de
pagamento e situações variadas:

- em dia (vencimento no futuro) e vence exatamente hoje;
- atrasado leve (3 e 5 dias) — com juros de R$ 5/dia;
- inadimplente (7 e 10 dias) — dispara o alerta de bloqueio do aparelho;
- semanal dentro da janela (venceu nesta semana, ainda não conta atraso);
- quitado (para de cobrar);
- contrato recém-cadastrado sem `proximo_vencimento` (sem base de cálculo).

Também mistura `status` salvo x `status_efetivo`: alguns contratos ficam com
o `status` "desatualizado" de propósito, para mostrar que a lista e as telas
recalculam a situação de hoje (o job diário que grava isso é da Fase 2).

As datas são relativas a HOJE, então as situações continuam valendo em
qualquer dia em que o comando rodar. É idempotente — usa `get_or_create` por
CPF (cliente) e por (cliente, apelido) (contrato); rodar de novo não duplica.
Use `--reset` para apagar antes só os registros de demonstração.

    .venv\\Scripts\\python.exe manage.py seed_demo
    .venv\\Scripts\\python.exe manage.py seed_demo --reset
"""

import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clientes.models import Cliente
from apps.contratos.models import Contrato

# 10 clientes — CPFs válidos (dígito verificador correto), telefones em E.164.
# Alguns sem endereço de propósito (campo opcional). O último não tem contrato.
CLIENTES = [
    {
        "cpf": "10433218100",
        "nome": "Maria Aparecida da Silva",
        "telefone_whatsapp": "+5583988123401",
        "endereco": "Rua das Acácias, 120 — Bancários, João Pessoa/PB",
    },
    {
        "cpf": "96001338914",
        "nome": "José Carlos Ferreira",
        "telefone_whatsapp": "+5583999452210",
        "endereco": "",
    },
    {
        "cpf": "08386379499",
        "nome": "Ana Beatriz Nogueira",
        "telefone_whatsapp": "+5584981237788",
        "endereco": "Av. Hermes da Fonseca, 900 — Tirol, Natal/RN",
    },
    {
        "cpf": "02654235114",
        "nome": "Francisco das Chagas Lima",
        "telefone_whatsapp": "+5583996710450",
        "endereco": "Sítio Volta — Zona Rural, Sapé/PB",
    },
    {
        "cpf": "16155940789",
        "nome": "Luciana Rocha Albuquerque",
        "telefone_whatsapp": "+5581988903312",
        "endereco": "Rua do Sol, 45 — Boa Viagem, Recife/PE",
    },
    {
        "cpf": "81618495950",
        "nome": "Rafael Menezes Souza",
        "telefone_whatsapp": "+5511976548890",
        "endereco": "",
    },
    {
        "cpf": "31034131656",
        "nome": "Patrícia Gomes de Andrade",
        "telefone_whatsapp": "+5583984556677",
        "endereco": "Rua João Pessoa, 300 — Centro, Campina Grande/PB",
    },
    {
        "cpf": "47525534144",
        "nome": "Edson Vieira dos Santos",
        "telefone_whatsapp": "+5521993124455",
        "endereco": "Rua Uruguai, 88 — Tijuca, Rio de Janeiro/RJ",
    },
    {
        "cpf": "92832764851",
        "nome": "Camila Torres Barbosa",
        "telefone_whatsapp": "+5583987019922",
        "endereco": "Loteamento Nova Esperança, Q. 12 — Bayeux/PB",
    },
    {
        "cpf": "35030564160",
        "nome": "Marcos Antônio Pereira",
        "telefone_whatsapp": "+5585999881020",
        "endereco": "Av. Beira Mar, 1500 — Meireles, Fortaleza/CE",
    },
]

CPFS_DEMO = [c["cpf"] for c in CLIENTES]

E = Contrato.Estrutura
S = Contrato.Status


def contratos_demo(hoje: datetime.date) -> list[dict]:
    """10 contratos com datas relativas a ``hoje`` (ver docstring do módulo)."""
    d = datetime.timedelta
    segunda_desta_semana = hoje - d(days=hoje.weekday())

    return [
        # Maria — 2 contratos (um ativo em dia, um já quitado).
        {
            "cpf": "10433218100",
            "apelido": "iPhone 11",
            "aparelho_modelo": "Apple iPhone 11 64GB",
            "imei": "356938035643809",
            "valor_total": Decimal("2400.00"),
            "estrutura": E.DIARIA,
            "valor_parcela": Decimal("40.00"),
            "num_parcelas": 60,
            "data_inicio": hoje - d(days=20),
            "dia_referencia": "todo dia",
            "proximo_vencimento": hoje + d(days=1),
            "status": S.EM_DIA,
            "data_prevista_quitacao": None,
            "observacoes": "Cliente pontual, nunca atrasou.",
        },
        {
            "cpf": "10433218100",
            "apelido": "Fone JBL",
            "aparelho_modelo": "JBL Tune 520BT",
            "imei": "",
            "valor_total": Decimal("350.00"),
            "estrutura": E.SEMANAL,
            "valor_parcela": None,
            "num_parcelas": None,
            "data_inicio": hoje - d(days=120),
            "dia_referencia": "",
            "proximo_vencimento": hoje - d(days=30),
            "status": S.QUITADO,
            "data_prevista_quitacao": hoje - d(days=25),
            "observacoes": "Quitado antes do prazo.",
        },
        # José Carlos — mensal, atraso leve (3 dias). `status` salvo desatualizado.
        {
            "cpf": "96001338914",
            "apelido": "Moto G54",
            "aparelho_modelo": "Motorola Moto G54 5G 256GB",
            "imei": "",
            "valor_total": Decimal("1800.00"),
            "estrutura": E.MENSAL,
            "valor_parcela": Decimal("150.00"),
            "num_parcelas": 12,
            "data_inicio": hoje - d(days=90),
            "dia_referencia": "dia 5",
            "proximo_vencimento": hoje - d(days=3),
            "status": S.EM_DIA,  # desatualizado de propósito — a tela recalcula p/ Atrasado
            "data_prevista_quitacao": None,
            "observacoes": "",
        },
        # Ana Beatriz — quinzenal, inadimplente (10 dias) → alerta de bloqueio.
        {
            "cpf": "08386379499",
            "apelido": "iPhone 13",
            "aparelho_modelo": "Apple iPhone 13 128GB",
            "imei": "353247104812905",
            "valor_total": Decimal("3600.00"),
            "estrutura": E.QUINZENAL,
            "valor_parcela": None,
            "num_parcelas": None,
            "data_inicio": hoje - d(days=60),
            "dia_referencia": "dias 10 e 25",
            "proximo_vencimento": hoje - d(days=10),
            "status": S.ATRASADO,  # desatualizado — a tela recalcula p/ Inadimplente
            "data_prevista_quitacao": None,
            "observacoes": "Prometeu pagar e não apareceu. Cobrar de novo.",
        },
        # Francisco — por dezena, exatamente no limite de inadimplência (7 dias).
        {
            "cpf": "02654235114",
            "apelido": "Galaxy A05",
            "aparelho_modelo": "Samsung Galaxy A05 128GB",
            "imei": "",
            "valor_total": Decimal("1200.00"),
            "estrutura": E.DEZENA,
            "valor_parcela": None,
            "num_parcelas": 10,
            "data_inicio": hoje - d(days=40),
            "dia_referencia": "a cada 10 dias",
            "proximo_vencimento": hoje - d(days=7),
            "status": S.INADIMPLENTE,
            "data_prevista_quitacao": None,
            "observacoes": "Mora na zona rural — combinar visita.",
        },
        # Luciana — semanal DENTRO da janela: venceu nesta semana, ainda não conta atraso.
        {
            "cpf": "16155940789",
            "apelido": "Redmi Note 12",
            "aparelho_modelo": "Xiaomi Redmi Note 12 128GB",
            "imei": "",
            "valor_total": Decimal("1600.00"),
            "estrutura": E.SEMANAL,
            "valor_parcela": Decimal("100.00"),
            "num_parcelas": None,
            "data_inicio": hoje - d(days=14),
            "dia_referencia": "toda segunda",
            "proximo_vencimento": segunda_desta_semana,
            "status": S.EM_DIA,
            "data_prevista_quitacao": None,
            "observacoes": "Semanal sem dia fixo — conta a partir da segunda que vem.",
        },
        # Rafael — mensal, vence HOJE (ainda em dia, atraso só começa amanhã).
        {
            "cpf": "81618495950",
            "apelido": "iPhone 12",
            "aparelho_modelo": "Apple iPhone 12 64GB",
            "imei": "",
            "valor_total": Decimal("3000.00"),
            "estrutura": E.MENSAL,
            "valor_parcela": Decimal("250.00"),
            "num_parcelas": 12,
            "data_inicio": hoje - d(days=30),
            "dia_referencia": "",
            "proximo_vencimento": hoje,
            "status": S.EM_DIA,
            "data_prevista_quitacao": None,
            "observacoes": "",
        },
        # Patrícia — diária, atrasada (5 dias). `status` salvo desatualizado.
        {
            "cpf": "31034131656",
            "apelido": "Galaxy S21",
            "aparelho_modelo": "Samsung Galaxy S21 FE 256GB",
            "imei": "351824117723640",
            "valor_total": Decimal("2800.00"),
            "estrutura": E.DIARIA,
            "valor_parcela": None,
            "num_parcelas": None,
            "data_inicio": hoje - d(days=25),
            "dia_referencia": "todo dia",
            "proximo_vencimento": hoje - d(days=5),
            "status": S.EM_DIA,  # desatualizado — a tela recalcula p/ Atrasado
            "data_prevista_quitacao": None,
            "observacoes": "Acordo verbal: paga toda sexta.\nFaltou duas semanas seguidas — cobrar pessoalmente.",
        },
        # Edson — quinzenal recém-cadastrado, SEM próximo vencimento (sem base de cálculo).
        {
            "cpf": "47525534144",
            "apelido": "Poco X5",
            "aparelho_modelo": "Xiaomi Poco X5 5G 256GB",
            "imei": "",
            "valor_total": Decimal("1500.00"),
            "estrutura": E.QUINZENAL,
            "valor_parcela": None,
            "num_parcelas": None,
            "data_inicio": hoje - d(days=2),
            "dia_referencia": "",
            "proximo_vencimento": None,
            "status": S.EM_DIA,
            "data_prevista_quitacao": None,
            "observacoes": "Falta combinar as datas de vencimento com o Alisson.",
        },
        # Camila — mensal, tudo preenchido, folgado (vence daqui a 12 dias).
        {
            "cpf": "92832764851",
            "apelido": "iPhone 14",
            "aparelho_modelo": "Apple iPhone 14 128GB",
            "imei": "359217885540132",
            "valor_total": Decimal("4200.00"),
            "estrutura": E.MENSAL,
            "valor_parcela": Decimal("350.00"),
            "num_parcelas": 12,
            "data_inicio": hoje - d(days=18),
            "dia_referencia": "dia 5",
            "proximo_vencimento": hoje + d(days=12),
            "status": S.EM_DIA,
            "data_prevista_quitacao": hoje + d(days=330),
            "observacoes": "",
        },
    ]


class Command(BaseCommand):
    help = "Cria 10 clientes e 10 contratos de demonstração (situações variadas)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Apaga os clientes/contratos de demonstração antes de recriar.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            n_ct, _ = Contrato.objects.filter(cliente__cpf__in=CPFS_DEMO).delete()
            n_cl, _ = Cliente.objects.filter(cpf__in=CPFS_DEMO).delete()
            self.stdout.write(f"reset: removidos {n_cl} cliente(s) e {n_ct} contrato(s) de demo.")

        clientes_por_cpf: dict[str, Cliente] = {}
        criados_cli = 0
        for dados in CLIENTES:
            obj, criou = Cliente.objects.get_or_create(
                cpf=dados["cpf"],
                defaults={
                    "nome": dados["nome"],
                    "telefone_whatsapp": dados["telefone_whatsapp"],
                    "endereco": dados["endereco"],
                },
            )
            clientes_por_cpf[dados["cpf"]] = obj
            criados_cli += criou

        hoje = datetime.date.today()
        criados_ct = 0
        for dados in contratos_demo(hoje):
            cpf = dados.pop("cpf")
            apelido = dados.pop("apelido")
            _, criou = Contrato.objects.get_or_create(
                cliente=clientes_por_cpf[cpf],
                apelido=apelido,
                defaults=dados,
            )
            criados_ct += criou

        self.stdout.write(
            self.style.SUCCESS(
                f"OK — clientes: {criados_cli} novo(s) / {len(CLIENTES)} no total de demo; "
                f"contratos: {criados_ct} novo(s) / 10 no total de demo. "
                "'Marcos Antônio Pereira' fica sem contrato de propósito."
            )
        )
