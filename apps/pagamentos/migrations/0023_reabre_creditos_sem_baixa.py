from decimal import Decimal

from django.db import migrations
from django.db.models import F


def reabrir_creditos_sem_baixa(apps, schema_editor):
    """Corrige parcelas zeradas por um pagamento já estornado.

    Parcelas que receberam o troco de uma baixa maior ficavam como pagas com
    valor zero e sem registro próprio. Se a baixa de origem já foi estornada,
    não existe mais crédito ativo que justifique esse estado.
    """
    Contrato = apps.get_model("contratos", "Contrato")
    Vencimento = apps.get_model("pagamentos", "Vencimento")

    contratos = Contrato.objects.filter(
        vencimentos__status="pago",
        vencimentos__valor_previsto=Decimal("0.00"),
        vencimentos__valor_pago=Decimal("0.00"),
    ).distinct()
    for contrato in contratos.iterator():
        if Vencimento.objects.filter(
            contrato_id=contrato.pk,
            pagamentos__isnull=False,
            valor_pago__gt=F("valor_previsto"),
        ).exists():
            continue
        parcelas = Vencimento.objects.filter(
            contrato_id=contrato.pk,
            status="pago",
            valor_previsto=Decimal("0.00"),
            valor_pago=Decimal("0.00"),
            pagamentos__isnull=True,
        )
        for parcela in parcelas:
            parcela.valor_previsto = contrato.valor_parcela + parcela.acrescimo
            parcela.status = "aberto"
            parcela.save(update_fields=["valor_previsto", "status"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagamentos", "0022_grupo_whatsapp_visto"),
    ]

    operations = [
        migrations.RunPython(reabrir_creditos_sem_baixa, migrations.RunPython.noop),
    ]
