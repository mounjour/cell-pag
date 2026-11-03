from django.db import migrations


def devolver_saldo_a_parcela_de_origem(apps, schema_editor):
    """Baixas parciais antigas somaram o que faltou ao previsto da parcela seguinte. Pela regra nova o saldo fica
    na própria parcela, então devolve: tira o valor da seguinte e zera o ``saldo_repassado``.

    Só mexe quando é inequívoco: a seguinte ainda está sem pagamento e, sem o valor somado, volta a ser exatamente
    a parcela do contrato (mais o ajuste dela). Qualquer outro caso fica como está (saldo já repassado)."""
    Vencimento = apps.get_model("pagamentos", "Vencimento")
    for venc in Vencimento.objects.filter(saldo_repassado__gt=0).select_related("contrato").order_by("contrato_id", "numero"):
        seguinte = (
            Vencimento.objects.filter(contrato_id=venc.contrato_id, numero__gt=venc.numero).exclude(status="pago").order_by("numero").first()
        )
        if seguinte is None or seguinte.valor_pago or seguinte.pagamentos.exists():
            continue
        if seguinte.valor_previsto - venc.saldo_repassado != venc.contrato.valor_parcela + seguinte.acrescimo:
            continue
        seguinte.valor_previsto -= venc.saldo_repassado
        seguinte.save(update_fields=["valor_previsto"])
        venc.saldo_repassado = 0
        venc.save(update_fields=["saldo_repassado"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagamentos", "0019_parcial_continua_na_parcela"),
    ]

    operations = [
        migrations.RunPython(devolver_saldo_a_parcela_de_origem, migrations.RunPython.noop),
    ]
