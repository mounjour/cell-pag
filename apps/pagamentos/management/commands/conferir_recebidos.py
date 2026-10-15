"""Confere o extrato da Cora e dá baixa nos Pix recebidos (modo Pix estático).

Pode rodar de tempos em tempos (ex.: a cada 10 minutos) no agendador do servidor. Também roda sozinho
antes das cobranças do dia e quando a página "Pix recebidos direto" é aberta.
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.pagamentos import recebidos
from apps.pagamentos.models import RecebimentoCora


class Command(BaseCommand):
    help = "Lê o extrato da Cora e registra os pagamentos Pix recebidos (só leitura na Cora)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ignorar-antes", metavar="AAAA-MM-DD",
            help="Marca como ignoradas as entradas ainda não conferidas recebidas antes desta data "
                 "(não apaga nada; serve para o primeiro uso, que lê 30 dias de extrato).",
        )

    def handle(self, *args, **options):
        antes = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.VINCULADO).count()
        erro = recebidos.sincronizar(forcar=True)
        if erro:
            self.stdout.write(self.style.ERROR(erro))
            return
        if options["ignorar_antes"]:
            try:
                corte = datetime.date.fromisoformat(options["ignorar_antes"])
            except ValueError as exc:
                raise CommandError("Use a data no formato AAAA-MM-DD, ex.: 2026-10-13.") from exc
            ignoradas = RecebimentoCora.objects.filter(
                situacao=RecebimentoCora.Situacao.NOVO, recebido_em__date__lt=corte
            ).update(situacao=RecebimentoCora.Situacao.IGNORADO, tratado_em=timezone.now())
            self.stdout.write(f"{ignoradas} entrada(s) anteriores a {corte:%d/%m/%Y} marcadas como ignoradas.")
        baixados = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.VINCULADO).count() - antes
        pendentes = RecebimentoCora.objects.filter(situacao=RecebimentoCora.Situacao.NOVO).count()
        self.stdout.write(self.style.SUCCESS(f"Extrato conferido: {baixados} baixa(s) registrada(s), {pendentes} entrada(s) para a equipe conferir."))
