import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Renomeia CobrancaPix -> CobrancaCora e adiciona os campos de boleto.

    A Cora passa a emitir a mesma fatura com Pix **e** boleto; o modelo deixa de
    se chamar ``CobrancaPix`` para não induzir a erro. Cartão não entra agora.
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
        migrations.AddField(
            model_name="cobrancacora",
            name="metodo_pago",
            field=models.CharField(
                blank=True,
                choices=[("pix", "Pix"), ("boleto", "Boleto")],
                max_length=10,
                verbose_name="forma usada no pagamento",
            ),
        ),
        migrations.AddField(
            model_name="cobrancacora",
            name="boleto_url",
            field=models.URLField(blank=True, max_length=500, verbose_name="PDF/link do boleto"),
        ),
        migrations.AddField(
            model_name="cobrancacora",
            name="boleto_linha_digitavel",
            field=models.CharField(blank=True, max_length=60, verbose_name="linha digitável"),
        ),
        migrations.AddField(
            model_name="cobrancacora",
            name="boleto_codigo_barras",
            field=models.CharField(blank=True, max_length=60, verbose_name="código de barras"),
        ),
        migrations.AlterField(
            model_name="pagamento",
            name="forma",
            field=models.CharField(
                choices=[
                    ("pix", "Pix"),
                    ("boleto", "Boleto"),
                    ("dinheiro", "Dinheiro"),
                    ("outro", "Outro"),
                ],
                default="pix",
                max_length=10,
                verbose_name="forma de pagamento",
            ),
        ),
    ]
