"""Cancela o Pix (fatura da Cora) de uma parcela.

Nunca cancela fatura já paga. Exemplos:

    python manage.py cancelar_pix --vencimento 12
    python manage.py cancelar_pix --contrato 3          # todos os Pix em aberto do contrato
"""

from django.core.management.base import BaseCommand, CommandError

from apps.pagamentos import cora_api
from apps.pagamentos.models import CobrancaCora
from apps.pagamentos.pix_cora import CancelamentoRecusado, cancelar_cobranca


class Command(BaseCommand):
    help = "Cancela o Pix (fatura da Cora) de uma parcela ou de todas as parcelas em aberto de um contrato."

    def add_arguments(self, parser):
        parser.add_argument("--vencimento", type=int, help="pk da parcela (Vencimento).")
        parser.add_argument("--contrato", type=int, help="pk do contrato: cancela todos os Pix em aberto dele.")

    def handle(self, *args, **options):
        if bool(options["vencimento"]) == bool(options["contrato"]):
            raise CommandError("Informe --vencimento OU --contrato.")

        cobrancas = CobrancaCora.objects.select_related("vencimento__contrato")
        if options["vencimento"]:
            cobrancas = cobrancas.filter(vencimento_id=options["vencimento"])
        else:
            cobrancas = cobrancas.filter(vencimento__contrato_id=options["contrato"])
        cobrancas = cobrancas.exclude(status=CobrancaCora.Status.CANCELADO)
        if not cobrancas:
            raise CommandError("Nenhum Pix a cancelar para esse filtro.")

        falhas = 0
        for cobranca in cobrancas:
            rotulo = f"parcela {cobranca.vencimento.numero} do contrato {cobranca.vencimento.contrato_id}"
            try:
                cancelar_cobranca(cobranca)
            except (CancelamentoRecusado, cora_api.CoraErro) as exc:
                falhas += 1
                self.stdout.write(self.style.ERROR(f"{rotulo}: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"{rotulo}: Pix cancelado."))
        if falhas:
            raise CommandError(f"{falhas} Pix não foram cancelados.")
