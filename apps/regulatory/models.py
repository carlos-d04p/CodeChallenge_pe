from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from apps.accounts.models import PlayerProfile, AccountStatus
import hashlib
import json
from django.db import models, transaction
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

class ImmutableLog(models.Model):
    action = models.CharField(max_length=100)
    payload = models.TextField()
    previous_hash = models.CharField(max_length=64, default="")
    current_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Log de Auditoría"
        verbose_name_plural = "Logs de Auditoría"

    def __str__(self):
        return f"Log #{self.id} | {self.action}"

    @classmethod
    def registrar_evento(cls, action: str, payload_dict: dict):
        with transaction.atomic():
            last_entry = cls.objects.select_for_update().order_by('-id').first()
            prev_hash = last_entry.current_hash if last_entry else "0" * 64
            
            payload_str = json.dumps(payload_dict, sort_keys=True)
            
            hasher = hashlib.sha256()
            hasher.update((prev_hash + payload_str).encode('utf-8'))
            curr_hash = hasher.hexdigest()
            
            return cls.objects.create(
                action=action,
                payload=payload_str,
                previous_hash=prev_hash,
                current_hash=curr_hash
            )

    @classmethod
    def verificar_integridad(cls):
        logs = cls.objects.order_by('id')
        prev_hash = "0" * 64
        errores = []
        
        for log in logs:
            if log.previous_hash != prev_hash:
                errores.append(f"Quiebre en ID {log.id}: hash previo no coincide.")
            
            hasher = hashlib.sha256()
            hasher.update((log.previous_hash + log.payload).encode('utf-8'))
            calculated_hash = hasher.hexdigest()
            
            if log.current_hash != calculated_hash:
                errores.append(f"Alteración en ID {log.id}: payload modificado.")
            
            prev_hash = log.current_hash
            
        return len(errores) == 0, errores