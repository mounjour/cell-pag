from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Usuario(AbstractUser):
    """Usuário do sistema.

    Modelo de usuário customizado desde o início do projeto para evitar migração
    dolorosa depois. Por enquanto só acrescenta `perfil` ao usuário padrão do
    Django; o restante (nome, e-mail, senha, permissões) vem de `AbstractUser`.
    """

    class Perfil(models.TextChoices):
        FINANCEIRO = "financeiro", "Financeiro"
        DONO = "dono", "Dono"

    # Nome e e-mail são obrigatórios (o Django deixa ambos em branco por
    # padrão): o nome é o que aparece dentro do sistema e o e-mail serve para
    # entrar e para recuperar a senha.
    first_name = models.CharField("nome", max_length=150)
    email = models.EmailField("e-mail")

    REQUIRED_FIELDS = ["first_name", "email"]

    class Tema(models.TextChoices):
        CLARO = "claro", "Claro"
        ESCURO = "escuro", "Escuro"

    # Preferência de aparência, guardada na conta (vale em qualquer aparelho).
    tema = models.CharField(
        "tema", max_length=10, choices=Tema.choices, default=Tema.CLARO
    )

    # Aceite dos Termos de uso e privacidade: guarda qual versão do texto a
    # pessoa aceitou e quando. Mudou a versão (settings.TERMOS_VERSAO) → pede de novo.
    termos_aceitos_versao = models.CharField("versão dos termos aceita", max_length=20, blank=True)
    termos_aceitos_em = models.DateTimeField("termos aceitos em", null=True, blank=True)

    perfil = models.CharField(
        "perfil",
        max_length=20,
        choices=Perfil.choices,
        default=Perfil.FINANCEIRO,
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.nome_completo

    @property
    def nome_completo(self) -> str:
        """Nome (e sobrenome, se houver). Cai no login só para contas antigas
        que ainda não têm nome cadastrado."""
        return self.get_full_name() or self.username

    @property
    def nome_curto(self) -> str:
        """Só o primeiro nome — para a barra do sistema, onde falta espaço."""
        return self.first_name or self.username

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        if (
            self.email
            and Usuario.objects.filter(email__iexact=self.email)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({"email": "Já existe um usuário com este e-mail."})

    @property
    def is_dono(self) -> bool:
        """Perfil dono (ou superusuário). Vê tudo que o financeiro vê e mais."""
        return self.is_superuser or self.perfil == self.Perfil.DONO


class ConviteUsuario(models.Model):
    """Código de convite para cadastro rápido: o dono gera, a pessoa convidada
    usa a tela pública de cadastro uma única vez e cria o próprio usuário.

    O código é curto (alfabeto sem caracteres que se confundem), vale uma vez e
    expira. O perfil que a pessoa recebe é o escolhido na hora de gerar.
    """

    ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    TAMANHO = 8
    VALIDADE_HORAS = 48

    codigo = models.CharField("código", max_length=16, unique=True, editable=False)
    perfil = models.CharField(
        "perfil", max_length=20, choices=Usuario.Perfil.choices, default=Usuario.Perfil.FINANCEIRO
    )
    criado_por = models.ForeignKey(
        Usuario, verbose_name="criado por", null=True, on_delete=models.SET_NULL, related_name="convites_criados"
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    expira_em = models.DateTimeField("expira em")
    usado_em = models.DateTimeField("usado em", null=True, blank=True)
    usado_por = models.ForeignKey(
        Usuario, verbose_name="usado por", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="convite_de_cadastro",
    )
    revogado_em = models.DateTimeField("revogado em", null=True, blank=True)

    class Meta:
        verbose_name = "convite de usuário"
        verbose_name_plural = "convites de usuário"
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return self.codigo

    @classmethod
    def normalizar(cls, texto: str) -> str:
        """Aceita o código digitado com espaços, hífen ou minúsculas."""
        return "".join(c for c in (texto or "").upper() if c.isalnum())

    @classmethod
    def gerar(cls, criado_por, perfil, horas=None):
        import secrets
        from datetime import timedelta

        from django.utils import timezone

        horas = horas or cls.VALIDADE_HORAS
        while True:
            codigo = "".join(secrets.choice(cls.ALFABETO) for _ in range(cls.TAMANHO))
            if not cls.objects.filter(codigo=codigo).exists():
                break
        return cls.objects.create(
            codigo=codigo, perfil=perfil, criado_por=criado_por,
            expira_em=timezone.now() + timedelta(hours=horas),
        )

    @property
    def codigo_formatado(self) -> str:
        meio = len(self.codigo) // 2
        return f"{self.codigo[:meio]}-{self.codigo[meio:]}"

    @property
    def situacao(self) -> str:
        from django.utils import timezone

        if self.usado_em:
            return "usado"
        if self.revogado_em:
            return "cancelado"
        if self.expira_em <= timezone.now():
            return "expirado"
        return "valido"

    @property
    def esta_valido(self) -> bool:
        return self.situacao == "valido"
