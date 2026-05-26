from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from apps.accounts.utils import calcular_edad, validar_dni_peruano

class AccountStatus(models.TextChoices):
    PENDING = 'pendiente_verificacion', 'Pendiente de Verificación'
    VERIFIED = 'verificado', 'Verificado'
    BLOCKED = 'bloqueado', 'Bloqueado'
    SELF_EXCLUDED = 'autoexcluido', 'Autoexcluido'

class PlayerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    dni = models.CharField(max_length=8, unique=True)
    verification_digit = models.CharField(max_length=1)
    birth_date = models.DateField()
    status = models.CharField(
        max_length=25,
        choices=AccountStatus.choices,
        default=AccountStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        # 1. Validar Mayoría de Edad (Requisito Obligatorio)
        if self.birth_date and calcular_edad(self.birth_date) < 18:
            raise ValidationError("El usuario debe ser mayor de edad (>= 18 años) para registrarse.")

        # 2. Validar Algoritmo de Identidad Matemática (KYC)
        if self.dni and self.verification_digit:
            if not validar_dni_peruano(self.dni, self.verification_digit):
                raise ValidationError("El dígito verificador del DNI ingresado no es válido matemáticamente.")

    def save(self, *args, **kwargs):
        self.full_clean()  # Fuerza la ejecución de la lógica de validación de clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - DNI: {self.dni} [{self.status}]"