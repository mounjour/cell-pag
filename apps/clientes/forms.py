from django import forms

from .models import Cliente, so_digitos


class ClienteForm(forms.ModelForm):
    # max_length maior que o do modelo para aceitar CPF com máscara; normalizado em clean_cpf.
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "placeholder": "000.000.000-00", "data-mascara": "cpf", "autocomplete": "off"}
        ),
    )

    class Meta:
        model = Cliente
        fields = ["nome", "cpf", "telefone_whatsapp", "endereco"]
        widgets = {
            "nome": forms.TextInput(attrs={"autofocus": True}),
            "telefone_whatsapp": forms.TextInput(
                attrs={"inputmode": "tel", "placeholder": "(83) 99999-0000", "data-mascara": "telefone", "autocomplete": "off"}
            ),
            "endereco": forms.TextInput(attrs={"placeholder": "Opcional"}),
        }

    def clean_cpf(self) -> str:
        return so_digitos(self.cleaned_data.get("cpf", ""))
