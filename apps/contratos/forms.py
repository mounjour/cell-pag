import re
from decimal import Decimal, InvalidOperation

from django import forms

from .models import Contrato, DocumentoContrato


def moeda_para_decimal(valor):
    """Aceita '1.234,56', '1234,56' ou '1234.56' e devolve Decimal (ou None se vazio).

    Regras: se houver ',' e '.', o '.' é separador de milhar e a ',' é decimal.
    Se houver só ',', vira separador decimal. Se houver só '.', mantém como está.
    """
    if valor in (None, ""):
        return None
    texto = str(valor).strip().replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise forms.ValidationError("Informe um valor válido, ex.: 1.234,56.") from exc


class ContratoForm(forms.ModelForm):
    # Dinheiro entra como texto para aceitar vírgula decimal; convertido em clean_*.
    valor_total = forms.CharField(
        label="Valor total do contrato",
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
    )
    valor_parcela = forms.CharField(
        label="Valor da parcela",
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
    )

    class Meta:
        model = Contrato
        fields = [
            "cliente",
            "apelido",
            "aparelho_modelo",
            "imei",
            "valor_total",
            "estrutura",
            "valor_parcela",
            "num_parcelas",
            "data_inicio",
            "dia_referencia",
            "proximo_vencimento",
            "status",
            "data_prevista_quitacao",
            "observacoes",
        ]
        widgets = {
            "apelido": forms.TextInput(
                attrs={"autofocus": True, "placeholder": "Ex.: iPhone 11", "autocapitalize": "sentences"}
            ),
            "aparelho_modelo": forms.TextInput(
                attrs={"placeholder": "Ex.: iPhone 11 64GB", "autocapitalize": "sentences"}
            ),
            "imei": forms.TextInput(
                attrs={"inputmode": "numeric", "maxlength": "20", "placeholder": "15 dígitos (opcional)"}
            ),
            "num_parcelas": forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "step": "1"}),
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "proximo_vencimento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_prevista_quitacao": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "dia_referencia": forms.TextInput(attrs={"placeholder": "Ex.: dia 15  ·  a cada 10 dias"}),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("data_inicio", "proximo_vencimento", "data_prevista_quitacao"):
            self.fields[campo].input_formats = ["%Y-%m-%d"]
        # Ao editar, mostra os valores de dinheiro já formatados com vírgula.
        if self.instance and self.instance.pk:
            if self.instance.valor_total is not None:
                self.initial["valor_total"] = _formata_moeda(self.instance.valor_total)
            if self.instance.valor_parcela is not None:
                self.initial["valor_parcela"] = _formata_moeda(self.instance.valor_parcela)

    def clean_valor_total(self):
        valor = moeda_para_decimal(self.cleaned_data.get("valor_total"))
        if valor is None:
            raise forms.ValidationError("Informe o valor total do contrato.")
        return valor

    def clean_valor_parcela(self):
        return moeda_para_decimal(self.cleaned_data.get("valor_parcela"))

    def clean_imei(self):
        return re.sub(r"\D", "", self.cleaned_data.get("imei", ""))


def _formata_moeda(valor: Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",")


class DocumentoContratoForm(forms.ModelForm):
    class Meta:
        model = DocumentoContrato
        fields = ["tipo", "arquivo", "descricao"]
        widgets = {
            "descricao": forms.TextInput(attrs={"placeholder": "Opcional"}),
        }
