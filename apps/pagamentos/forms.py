"""Formulário de baixa de pagamento (Fase 3)."""

from django import forms
from django.utils import timezone

from apps.contratos.forms import moeda_para_decimal

from .models import Pagamento, Vencimento


class PagamentoForm(forms.ModelForm):
    # Dinheiro entra como texto para aceitar vírgula decimal (mesmo padrão do
    # ContratoForm); convertido em clean_valor_pago.
    valor_pago = forms.CharField(
        label="Valor pago",
        widget=forms.TextInput(
            attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}
        ),
    )

    class Meta:
        model = Pagamento
        fields = ["vencimento", "data_pagamento", "valor_pago", "forma", "comprovante", "observacao"]
        widgets = {
            "data_pagamento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacao": forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional"}),
        }

    def __init__(self, *args, contrato=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.contrato = contrato
        self.fields["data_pagamento"].input_formats = ["%Y-%m-%d"]

        abertas = (
            contrato.vencimentos.exclude(status=Vencimento.Status.PAGO).order_by("numero")
            if contrato is not None
            else Vencimento.objects.none()
        )
        self.fields["vencimento"].queryset = abertas
        self.fields["vencimento"].label = "Parcela"
        self.fields["vencimento"].empty_label = None
        self.fields["vencimento"].label_from_instance = self._rotulo_parcela

        if not self.is_bound and abertas:
            primeira = abertas.first()
            self.initial.setdefault("vencimento", primeira.pk)
            self.initial.setdefault("valor_pago", _formata_moeda(primeira.saldo))
            self.initial.setdefault("data_pagamento", timezone.localdate())

    @staticmethod
    def _rotulo_parcela(venc: Vencimento) -> str:
        return (
            f"Parcela {venc.numero} · vence {venc.data_vencimento:%d/%m/%Y} · "
            f"falta R$ {venc.saldo:.2f}".replace(".", ",")
        )

    def clean_valor_pago(self):
        valor = moeda_para_decimal(self.cleaned_data.get("valor_pago"))
        if valor is None or valor <= 0:
            raise forms.ValidationError("Informe um valor pago maior que zero.")
        return valor

    def clean_data_pagamento(self):
        data = self.cleaned_data.get("data_pagamento")
        if data and data > timezone.localdate():
            raise forms.ValidationError("A data do pagamento não pode ser no futuro.")
        return data

    def clean_vencimento(self):
        venc = self.cleaned_data.get("vencimento")
        if venc is not None and venc.pagamentos.exists():
            baixa = venc.pagamentos.first()
            raise forms.ValidationError(
                f"A parcela {venc.numero} já recebeu baixa em "
                f"{baixa.data_pagamento:%d/%m/%Y} (R$ {baixa.valor_pago:.2f}). "
                "Estorne a baixa existente antes de lançar outra."
            )
        return venc


def _formata_moeda(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")
