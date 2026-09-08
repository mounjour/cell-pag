import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Renomeia CobrancaPix -> CobrancaCora.

    A cobrança da Cora continua sendo só Pix (boleto e cartão ficam de fora); o
    modelo passa a se chamar ``CobrancaCora`` por ser o registro da integração
    com a Cora, não uma amarra ao Pix.
    """

    dependencies = [("pagamentos", "0004_cobrancapix_eventocora")]

    operations = [
        migrations.RenameModel(old_name="CobrancaPix", new_name="CobrancaCora"),
        migrations.AlterModelOptions(
            name="cobrancacora",
            options={
                "ordering": ["-data_vencimento", "vencimento__contrato__cliente__nome"],
                "verbose_name": "cobrança Cora",
                "verbose_name_plural": "cobranças Cora",
            },
        ),
        migrations.AlterField(
            model_name="cobrancacora",
            name="vencimento",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cobranca_cora",
                to="pagamentos.vencimento",
            ),
        ),
    ]
