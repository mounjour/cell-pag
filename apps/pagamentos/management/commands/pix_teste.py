"""Gera um código Pix copia e cola de teste com a configuração atual (chave, nome e cidade do recebedor).

    python manage.py pix_teste              # R$ 0,01
    python manage.py pix_teste --valor 5

Cole o código no app do banco: confira se o nome e a chave mostrados são os esperados e pague o valor de teste;
o pagamento aparece no extrato da Cora e na página "Pix recebidos direto" (entrada sem cliente, que você pode ignorar).
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.pagamentos import brcode


class Command(BaseCommand):
    help = "Mostra um código Pix copia e cola de teste (R$ 0,01 por padrão)."

    def add_arguments(self, parser):
        parser.add_argument("--valor", default="0.01", help="valor em reais, ex.: 0.01")

    def handle(self, *args, **options):
        try:
            valor = Decimal(options["valor"].replace(",", "."))
            codigo = brcode.copia_e_cola(
                chave=settings.PIX_CHAVE, valor=valor, nome=settings.PIX_RECEBEDOR_NOME,
                cidade=settings.PIX_RECEBEDOR_CIDADE, referencia="TESTE",
            )
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Chave: {settings.PIX_CHAVE}")
        self.stdout.write(f"Recebedor: {settings.PIX_RECEBEDOR_NOME} — {settings.PIX_RECEBEDOR_CIDADE}")
        self.stdout.write(f"Valor: R$ {valor:.2f}")
        self.stdout.write("")
        self.stdout.write(codigo)
