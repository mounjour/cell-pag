import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import models

from apps.aparelhos.models import Aparelho

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
            "aparelho",
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

    # Só usado no cadastro (contrato em andamento antes de entrar no sistema)
    # — não é campo do modelo, o ModelForm ignora ele no save().
    parcelas_ja_pagas = forms.IntegerField(
        label="Parcelas já pagas antes do cadastro",
        required=False,
        min_value=0,
        max_value=10000,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "0", "step": "1"}),
        help_text=(
            "Se o contrato já estava em andamento antes de entrar no sistema, "
            "informe quantas das primeiras parcelas já foram pagas. Elas são "
            "registradas como pagas na própria data de vencimento e saem da "
            "cobrança automática. Deixe em branco ou 0 se é um contrato novo."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("data_inicio", "proximo_vencimento", "data_prevista_quitacao"):
            self.fields[campo].input_formats = ["%Y-%m-%d"]
        self.fields["num_parcelas"].required = False
        # Estoque: só aparelhos ainda não vendidos — mais o já vinculado a este
        # contrato (senão ele some da lista ao editar). Escolher um aqui não
        # dispensa preencher modelo/IMEI abaixo (o JS só sugere/preenche).
        atual = self.instance.aparelho_id if self.instance and self.instance.pk else None
        self.fields["aparelho"].queryset = Aparelho.objects.filter(
            models.Q(contrato__isnull=True) | models.Q(pk=atual)
        )
        self.fields["aparelho"].label = "Aparelho do estoque (opcional)"
        self.fields["aparelho"].required = False
        self.fields["aparelho"].help_text = (
            "Vincula a um aparelho já cadastrado no estoque — ele passa a "
            "aparecer como vendido. Ao escolher, modelo e IMEI abaixo são "
            "preenchidos sozinhos (confira antes de salvar)."
        )
        self.fields["aparelho"].widget.attrs["data-preenche-aparelho"] = "1"
        self.fields["aparelho"].empty_label = "Nenhum — digitar modelo/IMEI abaixo"
        if self.instance and self.instance.pk:
            # Só faz sentido ao cadastrar — parcelas de um contrato já
            # existente se registram pela tela de pagamento, uma a uma.
            del self.fields["parcelas_ja_pagas"]
        self.fields["num_parcelas"].help_text = (
            "Deixe em branco para calcular sozinho (valor total ÷ valor da "
            "parcela, arredondado para cima). Confira o total do plano na prévia; "
            "o valor da última parcela não é reduzido automaticamente."
        )
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

    def clean(self):
        dados = super().clean()
        quantidade = dados.get("parcelas_ja_pagas")
        num_parcelas = dados.get("num_parcelas")
        if quantidade and num_parcelas and quantidade > num_parcelas:
            self.add_error(
                "parcelas_ja_pagas",
                f"Não pode ser maior que o nº de parcelas ({num_parcelas}).",
            )
        return dados


def _formata_moeda(valor: Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",")


class DocumentoContratoForm(forms.ModelForm):
    class Meta:
        model = DocumentoContrato
        fields = ["tipo", "arquivo", "descricao"]
        widgets = {
            "descricao": forms.TextInput(attrs={"placeholder": "Opcional"}),
        }


class PrevisaoContratoForm(forms.Form):
    valor_total = forms.CharField()
    valor_parcela = forms.CharField()
    num_parcelas = forms.IntegerField(required=False, min_value=1, max_value=10000)
    estrutura = forms.ChoiceField(choices=Contrato.Estrutura.choices)
    data_inicio = forms.DateField(input_formats=["%Y-%m-%d"])

    def clean(self):
        dados = super().clean()
        for nome in ("valor_total", "valor_parcela"):
            if nome not in dados:
                continue
            valor = moeda_para_decimal(dados[nome])
            if valor is None or not valor.is_finite() or valor <= 0 or valor.as_tuple().exponent < -2:
                raise forms.ValidationError("Informe valores positivos com até duas casas decimais.")
            dados[nome] = valor
        return dados
