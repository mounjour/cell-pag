"""Rotina diária única — o que o cron do provedor chama uma vez por dia.

Roda, **nesta ordem** (a ordem importa: a agenda do lembrete e das cobranças
depende dos vencimentos recém-gerados):

1. ``gerar_vencimentos``      — gera parcelas ~60 dias à frente + sincroniza
                                status e data de quitação de todos os contratos;
2. ``enviar_lembrete_diario`` — resumo "quem cobrar hoje" para a Yslane;
3. ``enviar_cobrancas_clientes`` — reconcilia a Cora e prepara/envia as
                                mensagens de vencimento/atraso do dia.

Cada etapa é isolada: se uma falhar, as seguintes ainda rodam e o comando
termina com erro (código ≠ 0) para o provedor marcar a execução como falha.

Enquanto ``WHATSAPP_PROVIDER=log`` / ``CORA_PROVIDER=log`` (padrão), as etapas 2
e 3 só montam a fila e registram no log — nada sai do sistema.

    python manage.py rotina_diaria
    python manage.py rotina_diaria --hoje 2026-10-01 --dias 90
    python manage.py rotina_diaria --sem-cobrancas      # só vencimentos + lembrete
"""

import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Roda a rotina diária: gera vencimentos, lembra a Yslane e dispara as cobranças."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hoje",
            default=None,
            help="Data de referência AAAA-MM-DD (padrão: hoje). Útil em teste.",
        )
        parser.add_argument(
            "--dias",
            type=int,
            default=60,
            help="Horizonte de geração de vencimentos, em dias (padrão: 60).",
        )
        parser.add_argument(
            "--sem-cobrancas",
            action="store_true",
            help="Pula o envio de cobranças aos clientes (só gera vencimentos e o lembrete).",
        )

    def handle(self, *args, **options):
        hoje = options["hoje"]
        if hoje is not None:
            try:
                datetime.date.fromisoformat(hoje)
            except ValueError as exc:
                raise CommandError("--hoje precisa estar no formato AAAA-MM-DD.") from exc

        etapas = [
            ("gerar_vencimentos", {"dias": options["dias"], **({"hoje": hoje} if hoje else {})}),
            ("enviar_lembrete_diario", {**({"hoje": hoje} if hoje else {})}),
        ]
        if not options["sem_cobrancas"]:
            etapas.append(
                ("enviar_cobrancas_clientes", {**({"hoje": hoje} if hoje else {})})
            )

        falhas = []
        for nome, kwargs in etapas:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n>> {nome}"))
            try:
                call_command(nome, stdout=self.stdout, stderr=self.stderr, **kwargs)
            except Exception as exc:  # noqa: BLE001 — uma etapa não pode derrubar as outras
                falhas.append(nome)
                self.stderr.write(self.style.ERROR(f"[FALHOU] {nome}: {exc}"))

        if falhas:
            raise CommandError(
                "Rotina diária terminou com falha em: " + ", ".join(falhas)
            )
        self.stdout.write(self.style.SUCCESS("\n[OK] Rotina diária concluída."))
