from django import forms

from .models import Contrato, DocumentoContrato


class ContratoForm(forms.ModelForm):
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
            "fiador",
            "status",
            "data_prevista_quitacao",
            "observacoes",
        ]
        widgets = {
            "data_inicio": forms.DateInput(attrs={"type": "date"}),
            "data_prevista_quitacao": forms.DateInput(attrs={"type": "date"}),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }


class DocumentoContratoForm(forms.ModelForm):
    class Meta:
        model = DocumentoContrato
        fields = ["tipo", "arquivo", "descricao"]
