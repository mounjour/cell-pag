import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import models

from apps.aparelhos.models import Aparelho
from apps.aparelhos.catalogo import opcoes_modelos

from apps.pagamentos.models import Pagamento

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
    aparelho_modelo = forms.ChoiceField(label="Modelo do iPhone", choices=opcoes_modelos())
    # Dinheiro entra como texto para aceitar vírgula decimal; convertido em clean_*.
    valor_total = forms.CharField(
        label="Valor total do contrato",
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
    )
    juros_diario = forms.CharField(
        label="Juros diário", required=False, initial="5,00",
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "5,00", "class": "money"}),
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
            "juros_diario",
            "num_parcelas",
            "data_inicio",
            "dia_referencia",
            "status",
            "data_prevista_quitacao",
            "observacoes",
        ]
        widgets = {
            "apelido": forms.TextInput(
                attrs={"autofocus": True, "placeholder": "Ex.: iPhone 11", "autocapitalize": "sentences"}
            ),
            "imei": forms.TextInput(
                attrs={"inputmode": "numeric", "maxlength": "20", "placeholder": "15 dígitos"}
            ),
            "num_parcelas": forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "step": "1"}),
            "data_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
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

    # Também só no cadastro — vira um Pagamento sem parcela vinculada (ver
    # Pagamento.vencimento, nullable), o mesmo mecanismo usado pra registro
    # avulso. Fica fora de valor_total: aparelho R$1.000 financiado + R$200 de
    # entrada é um negócio de R$1.200, dos quais só R$1.000 são parcelados.
    entrada = forms.CharField(
        label="Entrada (opcional)",
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
        help_text=(
            "Valor recebido à vista no fechamento, somado ao valor total "
            "financiado (não é uma parcela). Ex.: aparelho de R$ 1.000 "
            "financiado + R$ 200 de entrada = negócio de R$ 1.200."
        ),
    )
    entrada_forma = forms.ChoiceField(
        label="Forma da entrada",
        choices=Pagamento.Forma.choices,
        required=False,
        initial=Pagamento.Forma.DINHEIRO,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("data_inicio", "data_prevista_quitacao"):
            self.fields[campo].input_formats = ["%Y-%m-%d"]
        self.fields["num_parcelas"].required = True
        self.fields["imei"].required = True
        # Estoque: só aparelhos ainda não vendidos — mais o já vinculado a este
        # contrato (senão ele some da lista ao editar). Escolher um aqui não
        # dispensa preencher modelo/IMEI abaixo (o JS só sugere/preenche).
        atual = self.instance.aparelho_id if self.instance and self.instance.pk else None
        self.fields["aparelho"].queryset = Aparelho.objects.filter(
            models.Q(contrato__isnull=True) | models.Q(pk=atual)
        )
        modelo_atual = self.instance.aparelho_modelo if self.instance and self.instance.pk else ""
        self.fields["aparelho_modelo"].choices = opcoes_modelos(
            atual=modelo_atual,
            estoque=self.fields["aparelho"].queryset.values_list("modelo", flat=True).distinct(),
        )
        self.fields["aparelho"].label = "Aparelho do estoque (opcional)"
        self.fields["aparelho"].required = False
        self.fields["aparelho"].help_text = (
            "Vincula a um aparelho já cadastrado no estoque — ele passa a "
            "aparecer como alocado. Ao escolher, modelo e IMEI abaixo são "
            "preenchidos sozinhos (confira antes de salvar)."
        )
        self.fields["aparelho"].widget.attrs["data-preenche-aparelho"] = "1"
        self.fields["aparelho"].empty_label = "Nenhum — digitar modelo/IMEI abaixo"
        if self.instance and self.instance.pk:
            # Só faz sentido ao cadastrar — parcelas de um contrato já
            # existente se registram pela tela de pagamento, uma a uma, e a
            # entrada (se esqueceram de lançar) também dá pra registrar à mão.
            del self.fields["parcelas_ja_pagas"]
            del self.fields["entrada"]
            del self.fields["entrada_forma"]
        self.fields["num_parcelas"].help_text = (
            "O valor de cada parcela é calculado sozinho: valor total ÷ nº de parcelas, "
            "arredondado para o múltiplo de R$ 0,10 mais próximo. Confira na prévia."
        )
        # Ao editar, mostra os valores de dinheiro já formatados com vírgula.
        if self.instance and self.instance.pk:
            if self.instance.valor_total is not None:
                self.initial["valor_total"] = _formata_moeda(self.instance.valor_total)
            self.initial["juros_diario"] = _formata_moeda(self.instance.juros_diario)

    def clean_valor_total(self):
        valor = moeda_para_decimal(self.cleaned_data.get("valor_total"))
        if valor is None:
            raise forms.ValidationError("Informe o valor total do contrato.")
        return valor

    def clean_juros_diario(self):
        valor = moeda_para_decimal(self.cleaned_data.get("juros_diario"))
        if valor is None:
            return Decimal("5.00")
        if valor < 0:
            raise forms.ValidationError("Informe um valor igual ou maior que zero.")
        return valor

    def clean_imei(self):
        imei = re.sub(r"\D", "", self.cleaned_data.get("imei") or "")
        if not imei:
            raise forms.ValidationError("Informe o IMEI do aparelho.")
        return imei

    def clean_entrada(self):
        bruto = self.cleaned_data.get("entrada")
        if not bruto:
            return None
        valor = moeda_para_decimal(bruto)
        if valor is None or valor <= 0:
            raise forms.ValidationError("Informe um valor de entrada maior que zero, ou deixe em branco.")
        return valor

    def clean(self):
        dados = super().clean()
        if dados.get("valor_total") and dados.get("num_parcelas"):
            # Não é campo do formulário: sai do total e do nº de parcelas.
            self.instance.valor_parcela = Contrato.valor_da_parcela(dados["valor_total"], dados["num_parcelas"])
        quantidade = dados.get("parcelas_ja_pagas")
        num_parcelas = dados.get("num_parcelas")
        if quantidade and num_parcelas and quantidade > num_parcelas:
            self.add_error(
                "parcelas_ja_pagas",
                f"Não pode ser maior que o nº de parcelas ({num_parcelas}).",
            )
        if dados.get("entrada") and not dados.get("entrada_forma"):
            self.add_error("entrada_forma", "Escolha a forma da entrada.")
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
    num_parcelas = forms.IntegerField(min_value=1, max_value=10000)
    estrutura = forms.ChoiceField(choices=Contrato.Estrutura.choices)
    data_inicio = forms.DateField(input_formats=["%Y-%m-%d"])

    def clean(self):
        dados = super().clean()
        if "valor_total" in dados:
            valor = moeda_para_decimal(dados["valor_total"])
            if valor is None or not valor.is_finite() or valor <= 0 or valor.as_tuple().exponent < -2:
                raise forms.ValidationError("Informe valores positivos com até duas casas decimais.")
            dados["valor_total"] = valor
            if dados.get("num_parcelas"):
                dados["valor_parcela"] = Contrato.valor_da_parcela(valor, dados["num_parcelas"])
        return dados


class PlanilhaPreviaForm(forms.Form):
    arquivo = forms.FileField(
        label="Planilha de contratos (.xlsx ou .csv)",
        help_text="A prévia não cadastra nem altera dados.",
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if not arquivo.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError("Envie um arquivo .xlsx ou .csv.")
        if arquivo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("A planilha deve ter no máximo 5 MB.")
        return arquivo


class ResolverImportacaoForm(forms.Form):
    cpf = forms.CharField(
        label="CPF",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "000.000.000-00", "data-mascara": "cpf"}),
    )
    telefone = forms.CharField(
        label="Telefone / WhatsApp",
        widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "(83) 99999-0000", "data-mascara": "telefone"}),
    )
    valor_total = forms.CharField(label="Valor total financiado")
    parcelas_ja_pagas = forms.IntegerField(label="Parcelas já pagas", min_value=0, required=False, initial=0)
