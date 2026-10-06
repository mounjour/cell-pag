from django import forms

from .models import Cliente, so_digitos

TAMANHO_MAX_CSV = 1024 * 1024  # 1 MB


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


class ImportarClientesForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo CSV de clientes",
        help_text="Colunas: nome, cpf e telefone (endereço é opcional). A prévia não cadastra nada.",
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith(".csv"):
            raise forms.ValidationError("Envie um arquivo .csv.")
        if arquivo.size > TAMANHO_MAX_CSV:
            raise forms.ValidationError("O arquivo deve ter no máximo 1 MB.")
        return arquivo
