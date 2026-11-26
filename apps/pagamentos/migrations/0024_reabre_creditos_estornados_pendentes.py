from decimal import Decimal

from django.db import migrations
from django.db.models import F


def reabrir_creditos_estornados_pendentes(apps, schema_editor):
    """Reexecuta o reparo para estornos feitos depois da migração anterior."""
    Contrato = apps.get_model("contratos", "Contrato")
    Vencimento = apps.get_model("pagamentos", "Vencimento")

    contratos = Contrato.objects.filter(
        vencimentos__status="pago",
        vencimentos__valor_previsto=Decimal("0.00"),
        vencimentos__valor_pago=Decimal("0.00"),
    ).distinct()
    for contrato in contratos.iterator():
        # Se ainda existe uma baixa maior que a parcela, o crédito continua
        # válido e as parcelas zeradas não devem ser reabertas.
        if Vencimento.objects.filter(
            contrato_id=contrato.pk,
            pagamentos__isnull=False,
            valor_pago__gt=F("valor_previsto"),
        ).exists():
            continue
        for parcela in Vencimento.objects.filter(
            contrato_id=contrato.pk,
            status="pago",
            valor_previsto=Decimal("0.00"),
            valor_pago=Decimal("0.00"),
            pagamentos__isnull=True,
        ):
            parcela.valor_previsto = contrato.valor_parcela + parcela.acrescimo
            parcela.status = "aberto"
            parcela.save(update_fields=["valor_previsto", "status"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagamentos", "0023_reabre_creditos_sem_baixa"),
    ]

    operations = [
        migrations.RunPython(reabrir_creditos_estornados_pendentes, migrations.RunPython.noop),
    ]
