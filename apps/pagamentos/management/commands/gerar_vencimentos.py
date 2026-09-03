"""Job diário da Fase 2: gera vencimentos à frente e sincroniza status/quitação.

Para cada contrato **não quitado**:

1. gera os `Vencimento` que faltam até ``hoje + --dias`` (padrão 60) —
   precisa de ``valor_parcela``;
2. recalcula ``data_prevista_quitacao`` (= data da última parcela) — precisa de
   ``num_parcelas``;
3. roda ``sincronizar_status()`` (Fase 4) para gravar o status calculado.

Roda hoje como *management command* + cron do provedor. Vira tarefa do
``Django-Q2`` só no endurecimento de produção (PLANO-DO-PROJETO.md, seções 9 e 13).

    .venv\\Scripts\\python.exe manage.py gerar_vencimentos
    .venv\\Scripts\\python.exe manage.py gerar_vencimentos --dias 90
    .venv\\Scripts\\python.exe manage.py gerar_vencimentos --hoje 2026-10-01
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.contratos.models import Contrato


class Command(BaseCommand):
    help = "Gera vencimentos ~60 dias à frente e sincroniza status e data de quitação."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=60,
            help="Horizonte de geração, em dias corridos (padrão: 60).",
        )
        parser.add_argument(
            "--hoje",
            type=str,
            default=None,
            help="Data de referência AAAA-MM-DD (padrão: hoje). Útil em teste.",
        )

    def handle(self, *args, **options):
        if options["dias"] < 1:
            raise CommandError("--dias precisa ser >= 1.")
        try:
            hoje = (
                datetime.date.fromisoformat(options["hoje"])
                if options["hoje"]
                else datetime.date.today()
            )
        except ValueError as exc:
            raise CommandError("--hoje precisa estar no formato AAAA-MM-DD.") from exc

        contratos = list(
            Contrato.objects.exclude(status=Contrato.Status.QUITADO)
        )
        n_venc = n_status = n_quit = n_sem_parcela = 0
        with transaction.atomic():
            for ct in contratos:
                if ct.valor_parcela is None:
                    n_sem_parcela += 1
                else:
                    n_venc += len(
                        ct.gerar_vencimentos(dias_a_frente=options["dias"], hoje=hoje)
                    )
                    n_quit += ct.atualizar_data_prevista_quitacao()
                n_status += ct.sincronizar_status(hoje=hoje)

        self.stdout.write(
            self.style.SUCCESS(
                f"OK — {len(contratos)} contrato(s) processado(s): "
                f"{n_venc} vencimento(s) novo(s), "
                f"{n_status} status atualizado(s), "
                f"{n_quit} data(s) de quitação recalculada(s), "
                f"{n_sem_parcela} sem valor da parcela (pulado na geração)."
            )
        )
