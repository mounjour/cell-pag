from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contratos", "0006_contrato_quitado_em"),
        ("pagamentos", "0002_pagamento"),
    ]

    operations = [
        migrations.CreateModel(
            name="Cobranca",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data_alvo", models.DateField(verbose_name="data da cobrança")),
                ("canal", models.CharField(choices=[("whatsapp", "WhatsApp")], default="whatsapp", max_length=12)),
                ("destinatario", models.CharField(max_length=20)),
                ("mensagem", models.TextField()),
                ("status", models.CharField(choices=[("pendente", "Pendente"), ("enviado", "Enviado"), ("entregue", "Entregue"), ("lido", "Lido"), ("erro", "Erro")], default="pendente", max_length=12)),
                ("id_externo", models.CharField(blank=True, db_index=True, max_length=160, verbose_name="ID no provedor")),
                ("erro", models.TextField(blank=True)),
                ("tentativas", models.PositiveSmallIntegerField(default=0)),
                ("enviado_em", models.DateTimeField(blank=True, null=True)),
                ("entregue_em", models.DateTimeField(blank=True, null=True)),
                ("lido_em", models.DateTimeField(blank=True, null=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("contrato", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cobrancas", to="contratos.contrato")),
                ("vencimento", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cobrancas", to="pagamentos.vencimento")),
            ],
            options={
                "ordering": ["-data_alvo", "contrato__cliente__nome"],
                "constraints": [models.UniqueConstraint(fields=("contrato", "data_alvo", "canal"), name="cobranca_unica_por_contrato_dia_canal")],
            },
        ),
    ]
