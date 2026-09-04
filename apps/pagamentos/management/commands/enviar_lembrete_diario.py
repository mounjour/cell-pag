"""Lembrete diário (Fase 2, Modalidade A) — WhatsApp da Yslane, às 08:30.

Monta a agenda de "quem cobrar hoje" e chama `apps.pagamentos.lembrete.enviar`.
**O envio ainda é um stub** — sem conta WhatsApp Business (Alisson, 04/09) —
então isto só mostra/loga o texto que seria mandado; ver
`apps/pagamentos/lembrete.py` para trocar pelo envio de verdade quando a conta
existir.

Rodar depois de `gerar_vencimentos` (senão a agenda usa `proximo_vencimento`
desatualizado). Os dois entram no cron do provedor / `Django-Q2` no deploy
(seção 13 do plano):

    .venv\\Scripts\\python.exe manage.py gerar_vencimentos
    .venv\\Scripts\\python.exe manage.py enviar_lembrete_diario
    .venv\\Scripts\\python.exe manage.py enviar_lembrete_diario --hoje 2026-10-01
"""

import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.pagamentos.lembrete import enviar_lembrete_diario


class Command(BaseCommand):
    help = "Monta e 'envia' (stub, sem conta WhatsApp Business ainda) o lembrete diário da Yslane."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hoje",
            type=str,
            default=None,
            help="Data de referência AAAA-MM-DD (padrão: hoje). Útil em teste.",
        )

    def handle(self, *args, **options):
        try:
            hoje = (
                datetime.date.fromisoformat(options["hoje"])
                if options["hoje"]
                else None
            )
        except ValueError as exc:
            raise CommandError("--hoje precisa estar no formato AAAA-MM-DD.") from exc

        texto = enviar_lembrete_diario(hoje=hoje)
        self.stdout.write(
            self.style.SUCCESS(
                "Lembrete montado (envio real pendente da conta WhatsApp Business):"
            )
        )
        try:
            self.stdout.write(texto)
        except UnicodeEncodeError:
            # Console sem UTF-8 (comum em cp1252/cp850 do Windows): mostra o
            # texto sem os emojis em vez de travar o comando. O que é enviado
            # de verdade (via `lembrete.enviar`) continua em UTF-8 completo.
            self.stdout.write(texto.encode("ascii", errors="replace").decode("ascii"))
