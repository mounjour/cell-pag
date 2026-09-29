import re

from django import forms

from apps.contratos.forms import moeda_para_decimal

from .models import Aparelho


def _formata_moeda(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")


class AparelhoForm(forms.ModelForm):
    # Mesmo padrão de dinheiro-como-texto do ContratoForm (aceita vírgula).
    custo = forms.CharField(
        label="Custo de compra (opcional)",
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
    )

    class Meta:
        model = Aparelho
        fields = ["modelo", "imei", "custo", "fornecedor", "data_compra", "observacoes"]
        widgets = {
            "modelo": forms.TextInput(
                attrs={"autofocus": True, "placeholder": "Ex.: iPhone 11 64GB", "autocapitalize": "sentences"}
            ),
            "imei": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": "20", "placeholder": "15 dígitos (opcional)"}),
            "fornecedor": forms.TextInput(attrs={"placeholder": "Opcional"}),
            "data_compra": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3, "placeholder": "Opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data_compra"].input_formats = ["%Y-%m-%d"]
        if self.instance and self.instance.pk and self.instance.custo is not None:
            self.initial["custo"] = _formata_moeda(self.instance.custo)

    def clean_custo(self):
        return moeda_para_decimal(self.cleaned_data.get("custo"))

    def clean_imei(self):
        imei = re.sub(r"\D", "", self.cleaned_data.get("imei") or "")
        return imei or None
