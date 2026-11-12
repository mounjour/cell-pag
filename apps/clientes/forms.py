from django import forms

from django.core.exceptions import ValidationError

from .models import Cliente, so_digitos, valida_grupo_whatsapp

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
        fields = ["nome", "cpf", "telefone_whatsapp", "grupo_whatsapp", "endereco"]
        widgets = {
            "nome": forms.TextInput(attrs={"autofocus": True}),
            "telefone_whatsapp": forms.TextInput(
                attrs={"inputmode": "tel", "placeholder": "(83) 99999-0000", "data-mascara": "telefone", "autocomplete": "off"}
            ),
            "endereco": forms.TextInput(attrs={"placeholder": "Opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._nomes_dos_grupos = {}
        from apps.pagamentos.whatsapp import grupos_do_whatsapp

        grupos = grupos_do_whatsapp()
        if grupos is None:
            return  # sem lista (simulação ou Evolution fora do ar): fica o campo de texto
        atual = self.instance.grupo_whatsapp if self.instance and self.instance.pk else ""
        opcoes = [("", "Sem grupo: usar o telefone do cliente")]
        for g in grupos:
            self._nomes_dos_grupos[g["id"]] = g["nome"]
            opcoes.append((g["id"], f"{g['nome']} ({g['participantes']} participantes)"))
        if atual and atual not in self._nomes_dos_grupos:  # o grupo gravado não aparece mais na lista: mantém a escolha
            opcoes.append((atual, f"{self.instance.grupo_whatsapp_nome or atual} (não encontrado agora)"))
        campo = self.fields["grupo_whatsapp"]
        self.fields["grupo_whatsapp"] = forms.ChoiceField(
            label=campo.label, required=False, choices=opcoes, help_text=campo.help_text,
        )
        # A lista da Evolution pode não trazer o grupo: dá para colar o identificador (aparece em Conexões > Grupos do WhatsApp).
        self.fields["grupo_whatsapp_manual"] = forms.CharField(
            label="Ou cole o identificador do grupo", required=False, max_length=60,
            help_text="Use se o grupo não estiver na lista acima. Termina em @g.us.",
        )
        self.order_fields(["nome", "cpf", "telefone_whatsapp", "grupo_whatsapp", "grupo_whatsapp_manual", "endereco"])

    def clean_cpf(self) -> str:
        return so_digitos(self.cleaned_data.get("cpf", ""))

    def clean(self):
        dados = super().clean()
        manual = (dados.get("grupo_whatsapp_manual") or "").strip()
        if manual:
            try:
                valida_grupo_whatsapp(manual)
            except ValidationError as exc:
                self.add_error("grupo_whatsapp_manual", exc)
            else:
                dados["grupo_whatsapp"] = manual
        return dados

    def save(self, commit=True):
        cliente = super().save(commit=False)
        grupo = self.cleaned_data.get("grupo_whatsapp") or ""
        if not grupo:
            cliente.grupo_whatsapp_nome = ""
        elif grupo in self._nomes_dos_grupos:
            cliente.grupo_whatsapp_nome = self._nomes_dos_grupos[grupo]
        elif self.cleaned_data.get("grupo_whatsapp_manual"):
            from apps.pagamentos.models import GrupoWhatsApp

            visto = GrupoWhatsApp.objects.filter(jid=grupo).first()
            cliente.grupo_whatsapp_nome = visto.nome if visto else ""
        if commit:
            cliente.save()
        return cliente


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
