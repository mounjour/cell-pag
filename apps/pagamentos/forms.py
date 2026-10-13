"""Formulário de baixa de pagamento (Fase 3)."""

from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.contratos.forms import moeda_para_decimal

from .models import ContatoDeCobranca, Pagamento, Vencimento


class PagamentoForm(forms.ModelForm):
    # Dinheiro entra como texto para aceitar vírgula decimal (mesmo padrão do
    # ContratoForm); convertido em clean_valor_pago / clean_juros_pago.
    valor_pago = forms.CharField(
        label="Valor da parcela recebido",
        widget=forms.TextInput(
            attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}
        ),
    )
    juros_pago = forms.CharField(
        label="Juros recebidos",
        required=False,
        widget=forms.TextInput(
            attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}
        ),
        help_text=(
            "O cliente paga a parcela mais o juros do atraso (já vem preenchido pelo "
            "cálculo de hoje). Fica registrado à parte — não altera o valor da parcela "
            "nem da próxima. Deixe 0,00 só se o combinado for outro."
        ),
    )

    class Meta:
        model = Pagamento
        fields = [
            "vencimento",
            "data_pagamento",
            "valor_pago",
            "juros_pago",
            "forma",
            "comprovante",
            "observacao",
        ]
        widgets = {
            "data_pagamento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacao": forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional"}),
        }

    def __init__(self, *args, contrato=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.contrato = contrato
        self.fields["data_pagamento"].input_formats = ["%Y-%m-%d"]

        abertas = (
            contrato.vencimentos.exclude(status=Vencimento.Status.PAGO)
            .exclude(pagamentos__isnull=False)  # já tem baixa — só via estorno (clean_vencimento)
            .order_by("numero")
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
            from .agenda import parcelas_a_cobrar

            juros = next(
                (p.juros for p in parcelas_a_cobrar(contrato, timezone.localdate()) if p.numero == primeira.numero),
                Decimal("0.00"),
            )
            self.initial.setdefault("juros_pago", _formata_moeda(juros))
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

    def clean_juros_pago(self):
        bruto = self.cleaned_data.get("juros_pago")
        if not bruto:
            return Decimal("0.00")
        valor = moeda_para_decimal(bruto)
        if valor is None or valor < 0:
            raise forms.ValidationError("Informe um valor de juros válido (ou deixe em branco).")
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


class ContatoDeCobrancaForm(forms.ModelForm):
    """Anota um contato de cobrança; quem prometeu pagar informa até quando."""

    class Meta:
        model = ContatoDeCobranca
        fields = ["tipo", "resultado", "promessa_para", "nota"]
        widgets = {
            "promessa_para": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "nota": forms.Textarea(attrs={"rows": 2, "maxlength": "500", "placeholder": "O que foi combinado? (opcional)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["promessa_para"].input_formats = ["%Y-%m-%d"]
        self.fields["promessa_para"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean(self):
        dados = super().clean()
        resultado = dados.get("resultado")
        data = dados.get("promessa_para")
        if resultado == ContatoDeCobranca.Resultado.PROMESSA:
            if not data:
                self.add_error("promessa_para", "Informe até quando o cliente prometeu pagar.")
            elif data < timezone.localdate():
                self.add_error("promessa_para", "A data prometida não pode estar no passado.")
        else:
            dados["promessa_para"] = None  # só a promessa tem data
            if resultado == ContatoDeCobranca.Resultado.OUTRO and not (dados.get("nota") or "").strip():
                self.add_error("nota", "Escreva o que aconteceu neste contato.")
        return dados


class AcordoPerdaoForm(forms.Form):
    """Perdoar (parte d)o juros do atraso de uma parcela."""

    juros = forms.CharField(
        label="Juros a perdoar (R$)",
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00", "class": "money"}),
    )
    nota = forms.CharField(
        label="Anotação (opcional)", required=False, max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: cliente em dia há 6 meses"}),
    )

    def clean_juros(self):
        try:
            valor = moeda_para_decimal(self.cleaned_data.get("juros"))
        except forms.ValidationError:
            raise forms.ValidationError("Informe um valor válido, ex.: 25,00.") from None
        if valor is None or valor <= 0:
            raise forms.ValidationError("Informe um valor maior que zero.")
        return valor


class AcordoNovaDataForm(forms.Form):
    """Marcar uma nova data de vencimento para a parcela."""

    nova_data = forms.DateField(
        label="Nova data de vencimento", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    nota = forms.CharField(
        label="Anotação (opcional)", required=False, max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: recebe o salário dia 20"}),
    )
