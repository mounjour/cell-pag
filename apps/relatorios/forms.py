import datetime

from django import forms
from django.utils import timezone


class PeriodoForm(forms.Form):
    PERIODO_CHOICES = [
        ("diario", "Diário"),
        ("semanal", "Semanal"),
        ("mensal", "Mensal"),
        ("personalizado", "Personalizado"),
    ]

    periodo = forms.ChoiceField(choices=PERIODO_CHOICES, required=False, initial="diario")
    referencia = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )

    def clean(self):
        dados = super().clean()
        periodo = dados.get("periodo") or "diario"
        referencia = dados.get("referencia") or timezone.localdate()

        if periodo == "diario":
            inicio = fim = referencia
        elif periodo == "semanal":
            inicio = referencia - datetime.timedelta(days=referencia.weekday())
            fim = inicio + datetime.timedelta(days=6)
        elif periodo == "mensal":
            inicio = referencia.replace(day=1)
            proximo_mes = (inicio.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            fim = proximo_mes - datetime.timedelta(days=1)
        else:
            inicio, fim = dados.get("inicio"), dados.get("fim")
            if not inicio or not fim:
                raise forms.ValidationError("Informe as datas inicial e final.")
            if fim < inicio:
                raise forms.ValidationError("A data final não pode ser anterior à inicial.")

        if (fim - inicio).days > 366:
            raise forms.ValidationError("O período máximo para um relatório é de 367 dias.")

        dados.update(periodo=periodo, referencia=referencia, inicio=inicio, fim=fim)
        return dados
