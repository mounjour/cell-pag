import re

from django import forms

from apps.contratos.forms import moeda_para_decimal

from .models import Aparelho
from .catalogo import opcoes_modelos

TAMANHO_MAX_CSV = 1024 * 1024  # 1 MB


def _formata_moeda(valor) -> str:
    return f"{valor:.2f}".replace(".", ",")


class AparelhoForm(forms.ModelForm):
    modelo = forms.ChoiceField(label="Modelo do iPhone", choices=opcoes_modelos())
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
            "imei": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": "20", "placeholder": "15 dígitos"}),
            "fornecedor": forms.TextInput(attrs={"placeholder": "Opcional"}),
            "data_compra": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3, "placeholder": "Opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        atual = self.instance.modelo if self.instance and self.instance.pk else ""
        self.fields["modelo"].choices = opcoes_modelos(atual=atual)
        self.fields["modelo"].widget.attrs["autofocus"] = True
        self.fields["data_compra"].input_formats = ["%Y-%m-%d"]
        self.fields["imei"].required = True
        self.fields["imei"].help_text = "15 dígitos. Obrigatório — também evita cadastrar o mesmo aparelho duas vezes."
        if self.instance and self.instance.pk and self.instance.custo is not None:
            self.initial["custo"] = _formata_moeda(self.instance.custo)

    def clean_custo(self):
        return moeda_para_decimal(self.cleaned_data.get("custo"))

    def clean_imei(self):
        imei = re.sub(r"\D", "", self.cleaned_data.get("imei") or "")
        if not imei:
            raise forms.ValidationError("Informe o IMEI do aparelho.")
        return imei


class ImportarAparelhosForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo CSV de aparelhos",
        help_text="Colunas: modelo e imei (custo, fornecedor, data da compra e observações são opcionais). A prévia não cadastra nada.",
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith(".csv"):
            raise forms.ValidationError("Envie um arquivo .csv.")
        if arquivo.size > TAMANHO_MAX_CSV:
            raise forms.ValidationError("O arquivo deve ter no máximo 1 MB.")
        return arquivo
