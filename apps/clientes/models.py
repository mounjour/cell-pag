import re

from django.core.exceptions import ValidationError
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField
from validate_docbr import CPF as CPFValidator


def valida_cpf(valor: str) -> None:
    """Valida dígitos verificadores do CPF (via validate-docbr)."""
    if not CPFValidator().validate(valor or ""):
        raise ValidationError("CPF inválido.", code="cpf_invalido")


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


class Cliente(models.Model):
    """Cliente que comprou um ou mais aparelhos a prazo.

    Campos conforme resposta R5 do roteiro: nome, CPF e telefone obrigatórios;
    endereço opcional. Um cliente pode ter vários contratos (ver app `contratos`).
    """

    nome = models.CharField("nome completo", max_length=150)
    cpf = models.CharField(
        "CPF",
        max_length=11,
        unique=True,
        validators=[valida_cpf],
        help_text="Somente números (11 dígitos).",
    )
    telefone_whatsapp = PhoneNumberField("telefone / WhatsApp", region="BR")
    endereco = models.CharField("endereço", max_length=255, blank=True)

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome

    def clean_fields(self, exclude=None) -> None:
        # Normaliza o CPF para dígitos ANTES de rodar os validadores de campo
        # (max_length e dígito verificador), então "000.000.000-00" é aceito.
        if self.cpf:
            self.cpf = so_digitos(self.cpf)
        super().clean_fields(exclude=exclude)

    @property
    def cpf_formatado(self) -> str:
        c = self.cpf
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else c

    @property
    def telefone_exibicao(self) -> str:
        """Telefone legível: ``(83) 98888-7777`` para BR, E.164 para o resto."""
        tel = self.telefone_whatsapp
        if not tel:
            return ""
        try:
            return tel.as_national if tel.country_code == 55 else tel.as_international
        except Exception:
            return str(tel)

    @property
    def whatsapp_url(self) -> str:
        """Link ``wa.me`` a partir do telefone (só dígitos do E.164)."""
        tel = self.telefone_whatsapp
        if not tel:
            return ""
        try:
            return f"https://wa.me/{so_digitos(tel.as_e164)}"
        except Exception:
            return ""

    @property
    def contratos_ativos(self):
        return self.contratos.exclude(status=self.contratos.model.Status.QUITADO)
