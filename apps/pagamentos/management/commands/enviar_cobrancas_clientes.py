import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.pagamentos.cobranca import processar_cobrancas
from apps.pagamentos.pix_cora import reconciliar_abertas


class Command(BaseCommand):
    help = "Prepara e envia as cobranças WhatsApp de vencimento/atraso do dia."

    def add_arguments(self, parser):
        parser.add_argument("--hoje", help="Data AAAA-MM-DD (padrão: hoje).")
        parser.add_argument(
            "--somente-preparar",
            action="store_true",
            help="Cria a fila sem chamar o provedor, mesmo quando a Meta está configurada.",
        )

    def handle(self, *args, **options):
        try:
            hoje = datetime.date.fromisoformat(options["hoje"]) if options["hoje"] else None
        except ValueError as exc:
            raise CommandError("--hoje precisa estar no formato AAAA-MM-DD.") from exc
        conciliacao = reconciliar_abertas()
        resultado = processar_cobrancas(
            hoje=hoje,
            somente_preparar=options["somente_preparar"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Cobranças processadas: "
                f"{resultado['preparadas']} preparada(s), "
                f"{resultado['enviadas']} enviada(s), "
                f"{resultado['simuladas']} simulada(s), "
                f"{resultado['erros']} erro(s), "
                f"{resultado['ignoradas']} já enviada(s). "
                f"Conciliação Cora: {conciliacao['consultadas']} consultada(s), "
                f"{conciliacao['pagas']} paga(s), {conciliacao['erros']} erro(s)."
            )
        )
