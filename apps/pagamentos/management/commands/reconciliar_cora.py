from django.core.management.base import BaseCommand

from apps.pagamentos.pix_cora import reconciliar_abertas


class Command(BaseCommand):
    help = "Confere na Cora as cobranças Pix abertas e registra baixas confirmadas."

    def handle(self, *args, **options):
        resultado = reconciliar_abertas()
        self.stdout.write(
            self.style.SUCCESS(
                f"Cora: {resultado['consultadas']} consultada(s), "
                f"{resultado['pagas']} paga(s), {resultado['erros']} erro(s)."
            )
        )
