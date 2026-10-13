import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import models

from apps.aparelhos.models import Aparelho
from apps.aparelhos.catalogo import opcoes_modelos
from apps.clientes.models import Cliente

from apps.pagamentos.models import Pagamento
from apps.pagamentos.recorrencia import (
    DIAS_DA_SEMANA, interpretar_dia_de_cobranca, primeira_cobranca_para_vencimento,
)

from .models import Contrato, DocumentoContrato

def calendario_em_andamento(estrutura, data_inicio, proxima, pagas, *, quinzena, dia_semana, dia_mes, dia_mes_2):
    """``(primeira_cobranca, dias_do_mes)`` de um contrato que já tem ``pagas`` parcelas pagas.

    O dado confiável é o vencimento da **próxima parcela** (a ``pagas + 1``-ésima): a primeira cobrança
    é reconstruída para trás a partir dele. Levanta ``ValueError`` com a mensagem para o usuário.
    """
    proxima, dias = interpretar_dia_de_cobranca(
        estrutura, data_inicio, primeira_cobranca=proxima, quinzena=quinzena or "semana",
        dia_semana=dia_semana, dia_mes=dia_mes, dia_mes_2=dia_mes_2,
    )
    return primeira_cobranca_para_vencimento(proxima, pagas, estrutura, dias), dias


#: Duas formas de cobrar quinzenalmente: a cada 14 dias (mesmo dia da semana) ou em dois dias fixos do mês.
QUINZENAS = [
    ("semana", "A cada 14 dias, no mesmo dia da semana"),
    ("dias_mes", "Dois dias fixos do mês (ex.: 5 e 20)"),
]


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
            "primeira_cobranca",
            "status",
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
            "primeira_cobranca": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }

    # Dia de cobrança: o usuário escolhe o dia da semana (ou do mês) e o sistema sugere a
    # primeira data; `primeira_cobranca` continua editável. Só `primeira_cobranca` e
    # `dias_cobranca_mes` são gravados — estes quatro campos só ajudam a escolher.
    quinzena = forms.ChoiceField(
        label="Como é a cobrança quinzenal?",
        required=False,
        choices=QUINZENAS,
        initial="semana",
    )
    dia_semana = forms.TypedChoiceField(
        label="Dia da semana da cobrança",
        required=False,
        choices=[("", "Escolha o dia…")] + [(str(i), nome.capitalize()) for i, nome in enumerate(DIAS_DA_SEMANA)],
        coerce=int,
        empty_value=None,
    )
    dia_mes = forms.IntegerField(
        label="Dia do mês da cobrança", required=False, min_value=1, max_value=31,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "max": "31", "placeholder": "Ex.: 15"}),
    )
    dia_mes_2 = forms.IntegerField(
        label="Segundo dia do mês", required=False, min_value=1, max_value=31,
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": "1", "max": "31", "placeholder": "Ex.: 20"}),
    )

    # Contrato que já estava rodando: o que se sabe é quando vence a PRÓXIMA parcela, não a primeira.
    proxima_cobranca = forms.DateField(
        label="Vencimento da próxima parcela", required=False, input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Quando vence a primeira parcela que ainda não foi paga. O sistema calcula o resto a partir dela.",
    )

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
        for campo in ("data_inicio",):
            self.fields[campo].input_formats = ["%Y-%m-%d"]
        self.fields["num_parcelas"].required = True
        self.fields["data_inicio"].label = "Data da compra"
        self.fields["primeira_cobranca"].label = "Primeira cobrança"
        self.fields["primeira_cobranca"].required = False
        self.fields["primeira_cobranca"].help_text = (
            "Dia em que vence a parcela 1. O sistema sugere a data a partir do dia de cobrança; "
            "altere se a primeira cobrança foi combinada em outra data."
        )
        self.fields["dia_semana"].help_text = "Dia da semana em que a parcela vence."
        self.fields["dia_mes"].help_text = "Em meses mais curtos, a cobrança cai no último dia do mês."
        self._valores_iniciais_do_dia_de_cobranca()
        # Estoque: só aparelhos ainda não vendidos — mais o já vinculado a este
        # contrato (senão ele some da lista ao editar).
        atual = self.instance.aparelho_id if self.instance and self.instance.pk else None
        self.fields["aparelho"].queryset = Aparelho.objects.filter(
            models.Q(contrato__isnull=True) | models.Q(pk=atual)
        )
        # Todo contrato novo sai de um aparelho do estoque: modelo e IMEI vêm dele.
        # Só um contrato antigo, criado antes do estoque e sem vínculo, continua
        # com modelo/IMEI digitados (e o vínculo opcional) ao ser editado.
        self.usa_estoque = not (self.instance and self.instance.pk and not self.instance.aparelho_id)
        if self.usa_estoque:
            del self.fields["aparelho_modelo"]
            del self.fields["imei"]
            self.fields["aparelho"].label = "Aparelho do estoque"
            self.fields["aparelho"].required = True
            self.fields["aparelho"].empty_label = "Escolha o aparelho…"
            self.fields["aparelho"].help_text = (
                "Só aparelhos disponíveis no estoque. Modelo e IMEI vêm do cadastro do aparelho; "
                "ao confirmar, ele passa a aparecer como alocado."
            )
        else:
            self.fields["imei"].required = True
            modelo_atual = self.instance.aparelho_modelo
            self.fields["aparelho_modelo"].choices = opcoes_modelos(
                atual=modelo_atual,
                estoque=self.fields["aparelho"].queryset.values_list("modelo", flat=True).distinct(),
            )
            self.fields["aparelho"].label = "Aparelho do estoque (opcional)"
            self.fields["aparelho"].required = False
            self.fields["aparelho"].help_text = (
                "Contrato antigo, sem vínculo com o estoque. Se escolher um aparelho, modelo e "
                "IMEI abaixo são preenchidos sozinhos (confira antes de salvar)."
            )
            self.fields["aparelho"].widget.attrs["data-preenche-aparelho"] = "1"
            self.fields["aparelho"].empty_label = "Nenhum — manter modelo/IMEI abaixo"
        self.entradas_existentes = []
        if self.instance and self.instance.pk:
            # "Parcelas já pagas" só faz sentido ao cadastrar: num contrato existente as parcelas
            # se registram pela tela de pagamento, uma a uma.
            del self.fields["parcelas_ja_pagas"]
            del self.fields["proxima_cobranca"]
            # A entrada é um pagamento sem parcela. Com 0 ou 1 lançamento dá para editar aqui
            # (esvaziar o valor remove a entrada); com vários, só pelo Admin, para não adivinhar qual mexer.
            self.entradas_existentes = list(self.instance.pagamentos.filter(vencimento__isnull=True))
            if len(self.entradas_existentes) > 1:
                del self.fields["entrada"]
                del self.fields["entrada_forma"]
            else:
                self.fields["entrada"].help_text = (
                    "Valor recebido à vista no fechamento. Corrija o valor ou a forma, ou apague o valor "
                    "para remover a entrada. Não é uma parcela."
                )
                if self.entradas_existentes:
                    atual = self.entradas_existentes[0]
                    self.initial["entrada"] = _formata_moeda(atual.valor_pago)
                    self.initial["entrada_forma"] = atual.forma
        self.fields["num_parcelas"].help_text = (
            "O valor de cada parcela é calculado sozinho: valor total ÷ quantidade de parcelas, "
            "arredondado para o múltiplo de R$ 0,10 mais próximo. Confira na prévia."
        )
        # Ao editar, mostra os valores de dinheiro já formatados com vírgula.
        if self.instance and self.instance.pk:
            if self.instance.valor_total is not None:
                self.initial["valor_total"] = _formata_moeda(self.instance.valor_total)
            self.initial["juros_diario"] = _formata_moeda(self.instance.juros_diario)

    def _valores_iniciais_do_dia_de_cobranca(self):
        """Ao editar, mostra o dia de cobrança já gravado nos campos de escolha."""
        contrato = self.instance
        if not (contrato and contrato.pk and contrato.primeira_cobranca):
            return
        dias = [int(d) for d in contrato.dias_cobranca_mes.split(",") if d]
        self.initial["quinzena"] = "dias_mes" if len(dias) >= 2 else "semana"
        self.initial["dia_semana"] = contrato.primeira_cobranca.weekday()
        if dias:
            self.initial["dia_mes"] = dias[0]
        if len(dias) >= 2:
            self.initial["dia_mes_2"] = dias[1]

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
        aparelho = dados.get("aparelho")
        if self.usa_estoque and aparelho:
            if not aparelho.imei:
                self.add_error("aparelho", "Este aparelho está sem IMEI no estoque. Edite o aparelho e informe o IMEI antes.")
            else:
                self.instance.aparelho_modelo = aparelho.modelo
                self.instance.imei = aparelho.imei
        if dados.get("valor_total") and dados.get("num_parcelas"):
            # Não é campo do formulário: sai do total e do nº de parcelas.
            self.instance.valor_parcela = Contrato.valor_da_parcela(dados["valor_total"], dados["num_parcelas"])
        quantidade = dados.get("parcelas_ja_pagas")
        num_parcelas = dados.get("num_parcelas")
        if quantidade and num_parcelas and quantidade > num_parcelas:
            self.add_error(
                "parcelas_ja_pagas",
                f"Não pode ser maior que a quantidade de parcelas ({num_parcelas}).",
            )
        if dados.get("entrada") and not dados.get("entrada_forma"):
            self.add_error("entrada_forma", "Escolha a forma da entrada.")
        self._resolver_dia_de_cobranca(dados)
        return dados

    def _calendario_em_andamento(self, dados, pagas):
        """Contrato com parcelas já pagas: o calendário parte do vencimento da próxima parcela."""
        if not dados.get("estrutura") or not dados.get("data_inicio") or self.errors.get("proxima_cobranca"):
            return
        proxima = dados.get("proxima_cobranca")
        if not proxima:
            self.add_error("proxima_cobranca", f"Informe quando vence a próxima parcela (a {pagas + 1}ª).")
            return
        try:
            primeira, dias = calendario_em_andamento(
                dados["estrutura"], dados["data_inicio"], proxima, pagas, quinzena=dados.get("quinzena"),
                dia_semana=dados.get("dia_semana"), dia_mes=dados.get("dia_mes"), dia_mes_2=dados.get("dia_mes_2"),
            )
        except ValueError as erro:
            campo = {"Informe o dia": "dia_mes", "Informe os dois": "dia_mes", "Escolha o dia da": "dia_semana"}
            alvo = next((c for prefixo, c in campo.items() if str(erro).startswith(prefixo)), "proxima_cobranca")
            self.add_error(alvo, str(erro).replace("A primeira cobrança", "O vencimento da próxima parcela"))
            return
        dados["primeira_cobranca"] = primeira
        self.instance.dias_cobranca_mes = dias

    def _resolver_dia_de_cobranca(self, dados):
        """Valida o dia de cobrança e completa a primeira cobrança (sugerida quando vazia)."""
        contrato = self.instance
        informou = any(
            dados.get(c) not in (None, "") for c in ("primeira_cobranca", "dia_semana", "dia_mes", "dia_mes_2")
        )
        pagas, total = dados.get("parcelas_ja_pagas") or 0, dados.get("num_parcelas") or 0
        if not contrato.pk and 0 < pagas < total:
            self._calendario_em_andamento(dados, pagas)
            return
        legado = bool(contrato.pk and not contrato.primeira_cobranca)
        if legado and not informou:
            return  # contrato antigo, sem dia de cobrança: continua contando pela data da compra
        if not dados.get("estrutura") or not dados.get("data_inicio") or self.errors.get("primeira_cobranca"):
            return
        try:
            primeira, dias = interpretar_dia_de_cobranca(
                dados["estrutura"], dados["data_inicio"], primeira_cobranca=dados.get("primeira_cobranca"),
                quinzena=dados.get("quinzena") or "semana", dia_semana=dados.get("dia_semana"),
                dia_mes=dados.get("dia_mes"), dia_mes_2=dados.get("dia_mes_2"),
            )
        except ValueError as erro:
            campo = {"Informe o dia": "dia_mes", "Informe os dois": "dia_mes", "Escolha o dia da": "dia_semana"}
            alvo = next((c for prefixo, c in campo.items() if str(erro).startswith(prefixo)), "primeira_cobranca")
            self.add_error(alvo, str(erro))
            return
        dados["primeira_cobranca"] = primeira
        contrato.dias_cobranca_mes = dias


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
    estrutura = forms.ChoiceField(choices=Contrato.ESTRUTURAS_ATIVAS)
    data_inicio = forms.DateField(input_formats=["%Y-%m-%d"])
    primeira_cobranca = forms.DateField(input_formats=["%Y-%m-%d"], required=False)
    proxima_cobranca = forms.DateField(input_formats=["%Y-%m-%d"], required=False)
    quinzena = forms.ChoiceField(choices=QUINZENAS, required=False)
    dia_semana = forms.TypedChoiceField(
        choices=[("", "")] + [(str(i), "") for i in range(7)], coerce=int, empty_value=None, required=False
    )
    dia_mes = forms.IntegerField(min_value=1, max_value=31, required=False)
    dia_mes_2 = forms.IntegerField(min_value=1, max_value=31, required=False)
    # Opcionais: só enriquecem o resumo ao vivo (a prévia antiga continua valendo sem eles).
    juros_diario = forms.CharField(required=False)
    parcelas_ja_pagas = forms.IntegerField(required=False, min_value=0, max_value=10000)
    entrada = forms.CharField(required=False)
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.all(), required=False)

    def clean_juros_diario(self):
        try:
            return moeda_para_decimal(self.cleaned_data.get("juros_diario")) or Decimal("5.00")
        except forms.ValidationError:
            return Decimal("5.00")

    def clean_entrada(self):
        try:
            valor = moeda_para_decimal(self.cleaned_data.get("entrada"))
        except forms.ValidationError:
            return None
        return valor if valor and valor > 0 else None

    def clean(self):
        dados = super().clean()
        if "valor_total" in dados:
            valor = moeda_para_decimal(dados["valor_total"])
            if valor is None or not valor.is_finite() or valor <= 0 or valor.as_tuple().exponent < -2:
                raise forms.ValidationError("Informe valores positivos com até duas casas decimais.")
            dados["valor_total"] = valor
            if dados.get("num_parcelas"):
                dados["valor_parcela"] = Contrato.valor_da_parcela(valor, dados["num_parcelas"])
        quinzena, dia_semana = dados.pop("quinzena", ""), dados.pop("dia_semana", None)
        dia_mes, dia_mes_2 = dados.pop("dia_mes", None), dados.pop("dia_mes_2", None)
        proxima = dados.pop("proxima_cobranca", None)
        pagas, total = dados.get("parcelas_ja_pagas") or 0, dados.get("num_parcelas") or 0
        if dados.get("estrutura") and dados.get("data_inicio") and 0 < pagas < total:
            if not proxima:
                raise forms.ValidationError(f"Informe quando vence a próxima parcela (a {pagas + 1}ª).")
            try:
                dados["primeira_cobranca"], dados["dias_cobranca_mes"] = calendario_em_andamento(
                    dados["estrutura"], dados["data_inicio"], proxima, pagas, quinzena=quinzena or "semana",
                    dia_semana=dia_semana, dia_mes=dia_mes, dia_mes_2=dia_mes_2,
                )
            except ValueError as erro:
                raise forms.ValidationError(str(erro)) from erro
        elif dados.get("estrutura") and dados.get("data_inicio"):
            try:
                dados["primeira_cobranca"], dados["dias_cobranca_mes"] = interpretar_dia_de_cobranca(
                    dados["estrutura"], dados["data_inicio"], primeira_cobranca=dados.get("primeira_cobranca"),
                    quinzena=quinzena or "semana", dia_semana=dia_semana, dia_mes=dia_mes, dia_mes_2=dia_mes_2,
                )
            except ValueError as erro:
                raise forms.ValidationError(str(erro)) from erro
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
