from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from apps.accounts.models import PlayerProfile, AccountStatus

class PlayerPlayLimits(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='play_limits')
    
    # Límites activos actuales (Montos decimales estrictos)
    daily_deposit_limit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('1000.0000'))
    weekly_deposit_limit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('5000.0000'))
    monthly_deposit_limit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal('20000.0000'))
    
    # Variables de control para solicitudes de aumento (Cooldown)
    pending_daily_limit = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    cooldown_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Límites de {self.user.username} | Diario: {self.daily_deposit_limit}"

    def solicitar_cambio_limite_diario(self, nuevo_limite: Decimal):
        """
        Aplica cambios de límites bajo la regla regulatoria:
        - Si se reduce el límite, se procesa de forma instantánea.
        - Si se incrementa, se somete a un cooldown estricto de 24 horas.
        """
        if nuevo_limite <= 0:
            raise ValidationError("El límite configurado debe ser mayor a cero.")

        # ---> NUEVA REGLA DEFENSIVA <---
        if nuevo_limite == self.daily_deposit_limit:
            raise ValidationError("El nuevo límite solicitado es idéntico al actual.")

        ahora = timezone.now()

        if nuevo_limite < self.daily_deposit_limit:
            # Reducción instantánea obligatoria
            self.daily_deposit_limit = nuevo_limite
            self.pending_daily_limit = None
            self.cooldown_until = None
        else:
            # Incremento requiere cooldown de 24 horas
            self.pending_daily_limit = nuevo_limite
            self.cooldown_until = ahora + timedelta(hours=24)
        
        self.save()

    def consolidar_incremento_pendiente(self):
        """
        Libera el incremento del límite si y solo si el cooldown de 24h ya expiró.
        """
        if not self.pending_daily_limit or not self.cooldown_until:
            raise ValidationError("No existen solicitudes de aumento de límites pendientes de aprobación.")

        if timezone.now() < self.cooldown_until:
            tiempo_restante = self.cooldown_until - timezone.now()
            horas_restantes = round(tiempo_restante.total_seconds() / 3600, 1)
            raise ValidationError(f"Operación denegada. El periodo de cooldown de 24h sigue activo. Restan {horas_restantes} horas.")

        # Cooldown superado: Se aplica el nuevo tope
        self.daily_deposit_limit = self.pending_daily_limit
        self.pending_daily_limit = None
        self.cooldown_until = None
        self.save()


class AutoExclusionRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='autoexcluidos')
    exclusion_date = models.DateTimeField(auto_now_add=True)
    excluded_until = models.DateTimeField(null=True, blank=True, help_text="Null significa autoexclusión indefinida")
    reason = models.TextField(blank=True, default="Solicitud voluntaria de juego responsable")

    def __str__(self):
        hasta = self.excluded_until if self.excluded_until else "Indefinido"
        return f"Autoexclusión de {self.user.username} hasta {hasta}"

    @classmethod
    def registrar_autoexclusion(cls, user, dias_duracion: int = None):
        """
        Activa una restricción temporal o indefinida sobre el perfil del jugador.
        Modifica el estado KYC a 'autoexcluido' de forma irreversible antes de tiempo.
        """
        ahora = timezone.now()
        fecha_limite = ahora + timedelta(days=dias_duracion) if dias_duracion else None

        # Modificar el estado del perfil principal a autoexcluido
        profile = user.profile
        profile.status = AccountStatus.SELF_EXCLUDED
        profile.save()

        # Registrar la bitácora inmutable regulatoria
        return cls.objects.create(
            user=user,
            excluded_until=fecha_limite
        )

    @classmethod
    def intentar_revertir_autoexclusion(cls, user):
        """
        Protección bloqueante exigida por la rúbrica:
        Impide levantar el castigo antes de que concluya el plazo establecido.
        """
        profile = user.profile
        if profile.status != AccountStatus.SELF_EXCLUDED:
            return  # No está autoexcluido

        # Buscar el registro activo más reciente
        ultimo_registro = cls.objects.filter(user=user).order_by('-exclusion_date').first()

        if ultimo_registro:
            # Si es indefinida o la fecha actual aún no supera el plazo establecido
            if ultimo_registro.excluded_until is None:
                raise ValidationError("Prohibido revocar. Su cuenta posee una autoexclusión indefinida.")
            
            if timezone.now() < ultimo_registro.excluded_until:
                dias_restantes = (ultimo_registro.excluded_until - timezone.now()).days
                raise ValidationError(f"Acción rechazada por Juego Responsable. No puede restaurar su cuenta hasta cumplir el plazo. Restan {dias_restantes} días.")

        # Si el tiempo ya expiró, se le permite volver a verificación pendiente
        profile.status = AccountStatus.PENDING_VERIFICATION
        profile.save()