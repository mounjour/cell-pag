"""Confere o extrato da Cora e dá baixa nos Pix recebidos (modo Pix estático).

Pode rodar de tempos em tempos (ex.: a cada 10 minutos) no agendador do servidor. Também roda sozinho
antes das cobranças do dia e quando a página "Pix recebidos direto" é aberta.
"""

from django.core.management.base import BaseCommand

from apps.pagamentos import recebidos
from apps.pagamentos.models import RecebimentoCora


class Command(BaseCommand):
    help = "Lê o extrato da Cora e registra os pagamentos Pix recebidos (só leitura na Cora)."

    def handle(self, *args, **options):
        antes = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.VINCULADO).count()
        erro = recebidos.sincronizar(forcar=True)
        if erro:
            self.stdout.write(self.style.ERROR(erro))
            return
        baixados = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.VINCULADO).count() - antes
        pendentes = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO).count()
        self.stdout.write(self.style.SUCCESS(f"Extrato conferido: {baixados} baixa(s) registrada(s), {pendentes} entrada(s) para a equipe conferir."))
