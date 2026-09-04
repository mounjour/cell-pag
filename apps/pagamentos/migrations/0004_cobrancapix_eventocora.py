import uuid
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("pagamentos", "0003_cobranca")]

    operations = [
        migrations.CreateModel(
            name="CobrancaPix",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("cora_id", models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ("status", models.CharField(choices=[("pendente", "Aguardando geração"), ("aberto", "Aguardando pagamento"), ("pago", "Pago"), ("vencido", "Não pago"), ("cancelado", "Cancelado"), ("erro", "Erro")], default="pendente", max_length=12)),
                ("valor", models.DecimalField(decimal_places=2, max_digits=10)),
                ("total_pago", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("data_vencimento", models.DateField()),
                ("pix_copia_e_cola", models.TextField(blank=True)),
                ("qr_code_url", models.URLField(blank=True, max_length=500)),
                ("erro", models.TextField(blank=True)),
                ("pago_em", models.DateTimeField(blank=True, null=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("vencimento", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="cobranca_pix", to="pagamentos.vencimento")),
            ],
            options={"verbose_name": "cobrança Pix", "verbose_name_plural": "cobranças Pix", "ordering": ["-data_vencimento", "vencimento__contrato__cliente__nome"]},
        ),
        migrations.CreateModel(
            name="EventoCora",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("evento_id", models.CharField(max_length=120, unique=True)),
                ("tipo", models.CharField(max_length=80)),
                ("recurso_id", models.CharField(db_index=True, max_length=120)),
                ("processado", models.BooleanField(default=False)),
                ("erro", models.TextField(blank=True)),
                ("recebido_em", models.DateTimeField(auto_now_add=True)),
                ("processado_em", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-recebido_em"]},
        ),
    ]
