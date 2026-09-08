"""Cria (e opcionalmente sincroniza) uma cobrança Cora de teste.

Serve para validar a Integração Direta da Cora ponta a ponta sem passar pela
agenda do dia: escolhe uma parcela em aberto, chama a API e mostra o que voltou
(status, cora_id, Pix copia e cola, linha digitável do boleto, erro).

Exemplos:

    python manage.py criar_cobranca_teste
    python manage.py criar_cobranca_teste --contrato 3
    python manage.py criar_cobranca_teste --vencimento 12 --sincronizar
"""

from django.core.management.base import BaseCommand, CommandError

from apps.pagamentos import cora_api
from apps.pagamentos.models import Vencimento
from apps.pagamentos.pix_cora import obter_ou_criar_cobranca, sincronizar_cobranca


class Command(BaseCommand):
    help = "Cria uma cobrança Cora (Pix + boleto) de teste para uma parcela em aberto."

    def add_arguments(self, parser):
        parser.add_argument("--contrato", type=int, help="pk do contrato (usa a 1ª parcela não paga).")
        parser.add_argument("--vencimento", type=int, help="pk exato do vencimento (tem prioridade).")
        parser.add_argument(
            "--sincronizar",
            action="store_true",
            help="Depois de criar, consulta a fatura na Cora (mostra pagamento se já houver).",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        self.stdout.write(f"CORA_PROVIDER = {settings.CORA_PROVIDER!r}")
        if settings.CORA_PROVIDER != "cora":
            self.stdout.write(
                self.style.WARNING(
                    "Modo diferente de 'cora': nenhuma chamada real será feita à Cora."
                )
            )
        else:
            try:
                cora_api.obter_token()
                self.stdout.write(self.style.SUCCESS("Token Cora obtido — credenciais e mTLS OK."))
            except cora_api.CoraErro as exc:
                raise CommandError(f"Falha ao obter token da Cora: {exc}") from exc

        vencimento = self._escolher_vencimento(options)
        self.stdout.write(
            f"Parcela: contrato {vencimento.contrato_id} — "
            f"{vencimento.contrato.apelido} — parcela {vencimento.numero} — "
            f"vence {vencimento.data_vencimento:%d/%m/%Y} — saldo R$ {vencimento.saldo}"
        )

        cobranca = obter_ou_criar_cobranca(vencimento)
        if options["sincronizar"] and cobranca.cora_id:
            sincronizar_cobranca(cobranca)
        cobranca.refresh_from_db()

        estilo = self.style.SUCCESS if cobranca.status != cobranca.Status.ERRO else self.style.ERROR
        self.stdout.write(estilo(f"status ......... {cobranca.get_status_display()}"))
        self.stdout.write(f"cora_id ........ {cobranca.cora_id or '—'}")
        self.stdout.write(f"pix copia/cola . {cobranca.pix_copia_e_cola[:60] or '—'}")
        self.stdout.write(f"boleto linha ... {cobranca.boleto_linha_digitavel or '—'}")
        self.stdout.write(f"boleto url ..... {cobranca.boleto_url or '—'}")
        if cobranca.total_pago:
            self.stdout.write(f"total pago ..... R$ {cobranca.total_pago} ({cobranca.get_metodo_pago_display() or 'forma não informada'})")
        if cobranca.erro:
            self.stdout.write(self.style.ERROR(f"erro ........... {cobranca.erro}"))
        self.stdout.write("Confira também em /pagamentos/pix/.")

    def _escolher_vencimento(self, options) -> Vencimento:
        if options["vencimento"]:
            try:
                return Vencimento.objects.select_related("contrato").get(pk=options["vencimento"])
            except Vencimento.DoesNotExist as exc:
                raise CommandError(f"Vencimento {options['vencimento']} não existe.") from exc

        qs = Vencimento.objects.select_related("contrato").exclude(
            status=Vencimento.Status.PAGO
        )
        if options["contrato"]:
            qs = qs.filter(contrato_id=options["contrato"])
        vencimento = qs.order_by("contrato_id", "numero").first()
        if vencimento is None:
            raise CommandError(
                "Nenhuma parcela em aberto encontrada"
                + (f" para o contrato {options['contrato']}." if options["contrato"] else ".")
            )
        return vencimento
