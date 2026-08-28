from django.core.validators import RegexValidator
from django.db import models

# TODO(Fase 1): trocar por validate-docbr (CPF) e django-phonenumber-field
# quando as dependências forem adicionadas — ver PLANO-DO-PROJETO.md, seção 13.
validador_cpf = RegexValidator(
    r"^\d{11}$",
    "Informe o CPF com 11 dígitos, apenas números.",
)


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
        validators=[validador_cpf],
        help_text="Somente números.",
    )
    telefone_whatsapp = models.CharField("telefone / WhatsApp", max_length=20)
    endereco = models.CharField("endereço", max_length=255, blank=True)

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome
