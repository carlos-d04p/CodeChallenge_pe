from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from decimal import Decimal
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone

class EventStatus(models.TextChoices):
    SCHEDULED = 'programado', 'Programado'
    LIVE = 'en_vivo', 'En Vivo'
    FINISHED = 'finalizado', 'Finalizado'
    SUSPENDED = 'suspendido', 'Suspendido'
    CANCELED = 'anulado', 'Anulado'

class MarketStatus(models.TextChoices):
    OPEN = 'abierto', 'Abierto'
    SUSPENDED = 'suspendido', 'Suspendido'
    CLOSED = 'cerrado', 'Cerrado'
    SETTLED = 'liquidado', 'Liquidado'

class SelectionResult(models.TextChoices):
    PENDING = 'pendiente', 'Pendiente'
    WON = 'ganador', 'Ganador'
    LOST = 'perdedor', 'Perdedor'
    VOID = 'anulado', 'Anulado'

class Event(models.Model):
    title = models.CharField(max_length=250, help_text="Nombre descriptivo del partido")
    home_team = models.CharField(max_length=100)
    away_team = models.CharField(max_length=100)
    kick_off = models.DateTimeField(help_text="Fecha y hora de inicio del partido")
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.SCHEDULED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['kick_off']

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} ({self.get_status_display()})"

    def cambiar_estado(self, nuevo_estado: EventStatus):
        """
        Máquina de estados explícita y segura para el flujo del partido.
        Evita saltos de estado ilegales en el flujo de juego.
        """
        transiciones_validas = {
            EventStatus.SCHEDULED: [EventStatus.LIVE, EventStatus.SUSPENDED, EventStatus.CANCELED],
            EventStatus.LIVE: [EventStatus.FINISHED, EventStatus.SUSPENDED, EventStatus.CANCELED],
            EventStatus.SUSPENDED: [EventStatus.LIVE, EventStatus.CANCELED],
            EventStatus.FINISHED: [],
            EventStatus.CANCELED: []
        }

        if nuevo_estado not in transiciones_validas.get(self.status, []):
            raise ValidationError(f"No se permite cambiar el partido de {self.get_status_display()} a {nuevo_estado}.")
        
        self.status = nuevo_estado
        self.save(update_fields=['status', 'updated_at'])


class Market(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='markets')
    name = models.CharField(max_length=100, default="Resultado Final (1X2)")
    code = models.CharField(max_length=20, default="1X2")
    status = models.CharField(max_length=20, choices=MarketStatus.choices, default=MarketStatus.OPEN)
    operator_margin = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.0500'))
    
    suspended_until = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('event', 'code')]

    def __str__(self):
        return f"{self.name} | {self.event.home_team} vs {self.event.away_team}"

    def suspender_por_incidente(self, segundos=15):
        self.status = MarketStatus.SUSPENDED
        self.suspended_until = timezone.now() + timezone.timedelta(seconds=segundos)
        self.save(update_fields=['status', 'suspended_until'])

    @property
    def is_betting_allowed(self):
        if self.status == MarketStatus.SUSPENDED and self.suspended_until:
            if timezone.now() >= self.suspended_until:
                self.status = MarketStatus.OPEN
                self.suspended_until = None
                self.save(update_fields=['status', 'suspended_until'])
                return True
            return False
        return self.status == MarketStatus.OPEN

class Selection(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='selections')
    name = models.CharField(max_length=50, help_text="Ej: Gana Local, Empate, Gana Visitante")
    odds = models.DecimalField(max_digits=18, decimal_places=4)
    result = models.CharField(
        max_length=20,
        choices=SelectionResult.choices,
        default=SelectionResult.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        """Validador matemático para asegurar cuotas consistentes en el sistema."""
        if self.odds is not None and self.odds <= Decimal('1.0000'):
            raise ValidationError("Las cuotas comerciales (odds) deben ser estrictamente superiores a 1.0000.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def actualizar_cuota(self, nueva_cuota: Decimal, user=None):
        if nueva_cuota <= Decimal('1.0000'):
            raise ValidationError("Las cuotas comerciales deben ser superiores a 1.0000.")
        
        old_odds = self.odds
        self.odds = nueva_cuota
        self.save(update_fields=['odds', 'updated_at'])
        
        OddsAuditRecord.objects.create(
            selection=self, old_odds=old_odds, new_odds=nueva_cuota, modified_by=user
        )
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"event_{self.market.event.id}",
                {
                    "type": "odds_update",
                    "data": {
                        "selection_id": self.id,
                        "old_odds": str(old_odds),
                        "new_odds": str(nueva_cuota)
                    }
                }
            )

    def __str__(self):
        return f"{self.name} @ {self.odds} ({self.get_result_display()})"


class OddsAuditRecord(models.Model):
    """
    MODELO DE AUDITORÍA COMPLIANCE (Nivel 3).
    Registra de forma inmutable cada vez que se alteran los precios de las cuotas.
    """
    selection = models.ForeignKey(Selection, on_delete=models.CASCADE, related_name='audit_records')
    old_odds = models.DecimalField(max_digits=18, decimal_places=4)
    new_odds = models.DecimalField(max_digits=18, decimal_places=4)
    modified_at = models.DateTimeField(auto_now_add=True)
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-modified_at']
        verbose_name = "Auditoría de Cuota"
        verbose_name_plural = "Auditoría de Cuotas"

    def __str__(self):
        return f"Cambio en {self.selection.name}: {self.old_odds} -> {self.new_odds}"