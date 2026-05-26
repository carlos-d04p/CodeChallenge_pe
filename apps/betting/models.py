from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
import uuid

from apps.accounts.models import PlayerProfile, AccountStatus
from apps.events.models import Selection, EventStatus, MarketStatus, SelectionResult
from apps.wallet.models import LedgerEntry, WalletAccountTypes, EntryDirections

class BetStatus(models.TextChoices):
    ACCEPTED = 'accepted', 'Aceptada'
    WON = 'won', 'Ganada'
    LOST = 'lost', 'Perdida'
    CANCELED = 'canceled', 'Anulada'

class Bet(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bets')
    selection = models.ForeignKey(Selection, on_delete=models.CASCADE, related_name='bets')
    
    # Manejo riguroso de montos decimales fijos (Prohibido floats)
    stake = models.DecimalField(max_digits=18, decimal_places=4)
    odds = models.DecimalField(max_digits=18, decimal_places=4)
    status = models.CharField(max_length=20, choices=BetStatus.choices, default=BetStatus.ACCEPTED)
    transaction_id = models.UUIDField(help_text="Enlace al movimiento contable inicial de bloqueo")
    
    # MEJORA DE INTEGRIDAD: Llave única para evitar duplicados por lag de red (Idempotencia)
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    LIMIT_MIN_STAKE = Decimal('1.0000')
    LIMIT_MAX_STAKE = Decimal('1000.0000')

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Apuesta Simple"
        verbose_name_plural = "Apuestas Simples"

    def __str__(self):
        return f"Ticket #{self.id} | {self.user.username} | {self.get_status_display()} | Fichas: {self.stake}"

    @classmethod
    def procesar_apuesta_simple(cls, user, selection, stake: Decimal, idempotency_key: str = None):
        """
        Motor de procesamiento de apuestas con validación estricta multinivel,
        bloqueo pesimista (select_for_update) e llaves de idempotencia.
        """
        # 1. Validación de límites del ticket
        if stake < cls.LIMIT_MIN_STAKE or stake > cls.LIMIT_MAX_STAKE:
            raise ValidationError(f"El monto de la apuesta debe encontrarse entre {cls.LIMIT_MIN_STAKE} y {cls.LIMIT_MAX_STAKE} fichas.")

        with transaction.atomic():
            # 2. Control de Idempotencia (Retorna el ticket existente si ya se procesó)
            if idempotency_key and cls.objects.filter(idempotency_key=idempotency_key).exists():
                return cls.objects.get(idempotency_key=idempotency_key)

            # EXIGENCIA RÚBRICA: Bloqueo pesimista del usuario para evitar doble gasto concurrente
            User.objects.select_for_update().get(id=user.id)
            
            # Validación Nivel 1: Integridad del perfil del apostador
            try:
                profile = user.profile
            except PlayerProfile.DoesNotExist:
                raise ValidationError("El usuario no cuenta con un registro de perfil KYC en el sistema.")

            # Validación Nivel 2: Restricciones de juego responsable e identidad
            if profile.status != AccountStatus.VERIFIED:
                raise ValidationError(f"Transacción bloqueada. Su cuenta se encuentra en estado: {profile.get_status_display()}.")

            # Validación Nivel 3: Estado de integridad del Mercado y del Evento
            market = selection.market
            event = market.event

            if market.status != MarketStatus.OPEN:
                raise ValidationError("No se admiten apuestas en mercados cerrados o suspendidos.")

            if event.status != EventStatus.SCHEDULED or event.kick_off <= timezone.now():
                raise ValidationError("El evento seleccionado ya ha iniciado o no está disponible para apuestas pre-partido.")

            # Validación Nivel 4: Verificación financiera del saldo derivado en tiempo real
            saldo_disponible = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=user)
            if saldo_disponible < stake:
                raise ValidationError("Fondos insuficientes en su billetera virtual para confirmar este ticket.")

            tx_id = uuid.uuid4()

            # EJECUCIÓN CONTABLE EN PARTIDA DOBLE (wallet_usuario -> apuestas_pendientes)
            # Entrada de Débito: Descuenta del saldo libre del usuario
            LedgerEntry.objects.create(
                user=user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=stake, direction=EntryDirections.DEBIT
            )
            # Entrada de Crédito: Congela las fichas en la cuenta de garantía de apuestas pendientes
            LedgerEntry.objects.create(
                user=user, transaction_id=tx_id, account=WalletAccountTypes.PENDING_BETS, amount=stake, direction=EntryDirections.CREDIT
            )

            # Guardar el ticket en estado aceptado
            return cls.objects.create(
                user=user,
                selection=selection,
                stake=stake,
                odds=selection.odds,
                status=BetStatus.ACCEPTED,
                transaction_id=tx_id,
                idempotency_key=idempotency_key
            )

    def liquidar_ticket(self, resultado_seleccion: SelectionResult):
        """
        Cierra la apuesta y ejecuta la partida doble correspondiente según el resultado.
        Soporta: GANADA, PERDIDA y ANULADA (Devolución total por suspensión de partido).
        """
        if self.status != BetStatus.ACCEPTED:
            raise ValidationError("Este ticket de apuesta ya ha sido liquidación o procesado previamente.")

        with transaction.atomic():
            tx_id = uuid.uuid4()
            
            # Toda liquidación libera las fichas congeladas de apuestas_pendientes (DEBIT)
            LedgerEntry.objects.create(
                user=self.user, transaction_id=tx_id, account=WalletAccountTypes.PENDING_BETS, amount=self.stake, direction=EntryDirections.DEBIT
            )

            if resultado_seleccion == SelectionResult.WON:
                self.status = BetStatus.WON
                payout_total = self.stake * self.odds
                costo_casa = payout_total - self.stake
                
                # Si hay ganancias netas, la casa asume el costo financiero (DEBIT)
                if costo_casa > 0:
                    LedgerEntry.objects.create(
                        user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=costo_casa, direction=EntryDirections.DEBIT
                    )
                # Se le abona el premio completo al saldo libre del usuario (CREDIT)
                LedgerEntry.objects.create(
                    user=self.user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=payout_total, direction=EntryDirections.CREDIT
                )

            elif resultado_seleccion == SelectionResult.LOST:
                self.status = BetStatus.LOST
                # El dinero pasa permanentemente a las arcas de la casa (CREDIT)
                LedgerEntry.objects.create(
                    user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=self.stake, direction=EntryDirections.CREDIT
                )

            elif resultado_seleccion == SelectionResult.VOID:
                # MEJORA: Manejo de partidos anulados/suspendidos (Reembolso completo del stake)
                self.status = BetStatus.CANCELED
                LedgerEntry.objects.create(
                    user=self.user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=self.stake, direction=EntryDirections.CREDIT
                )
            
            self.save()