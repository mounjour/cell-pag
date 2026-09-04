from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contratos", "0005_contrato_saldo_transportado")]

    operations = [
        migrations.AddField(
            model_name="contrato",
            name="quitado_em",
            field=models.DateField(
                blank=True,
                help_text="Data real em que o contrato foi marcado como quitado.",
                null=True,
                verbose_name="quitado em",
            ),
        ),
    ]
