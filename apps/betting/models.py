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

class BetType(models.TextChoices):
    SIMPLE = 'simple', 'Simple'
    COMBINED = 'combinada', 'Combinada'

class Bet(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bets')
    stake = models.DecimalField(max_digits=18, decimal_places=4)
    odds = models.DecimalField(max_digits=18, decimal_places=4)
    status = models.CharField(max_length=20, choices=BetStatus.choices, default=BetStatus.ACCEPTED)
    bet_type = models.CharField(max_length=20, choices=BetType.choices, default=BetType.SIMPLE)
    transaction_id = models.UUIDField()
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    LIMIT_MIN_STAKE = Decimal('1.0000')
    LIMIT_MAX_STAKE = Decimal('1000.0000')

    def ejecutar_cashout(self, odds_actual: Decimal, factor_casa: Decimal = Decimal('0.9500')):
        """
        Ejecuta el cierre anticipado calculando el retorno exacto con base en la fórmula:
        cashout = stake * odds_original / odds_actual * factor_casa
        """
        if self.status != BetStatus.ACCEPTED:
            raise ValidationError("Solo se puede realizar cash-out en apuestas aceptadas y activas.")
        
        if odds_actual <= Decimal('1.0000'):
            raise ValidationError("La cuota actual debe ser mayor a 1.0000.")

        with transaction.atomic():
            tx_id = uuid.uuid4()
            
            # Calcular retorno matemático exacto
            retorno_cashout = (self.stake * self.odds / odds_actual) * factor_casa
            # Forzar precisión a 4 decimales
            retorno_cashout = retorno_cashout.quantize(Decimal('0.0001'))

            # Cambiar estado del ticket
            self.status = BetStatus.CANCELED
            self.save(update_fields=['status', 'updated_at'])

            # CONTABILIDAD:
            # 1. Vaciar el stake original congelado en la cuenta de pendientes (DEBIT)
            LedgerEntry.objects.create(
                user=self.user, transaction_id=tx_id, account=WalletAccountTypes.PENDING_BETS, amount=self.stake, direction=EntryDirections.DEBIT
            )

            # 2. Devolver el valor calculado del cash-out al balance libre del usuario (CREDIT)
            LedgerEntry.objects.create(
                user=self.user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=retorno_cashout, direction=EntryDirections.CREDIT
            )

            # 3. Balancear la diferencia contable contra la cuenta del sistema (SYSTEM_HOUSE)
            # Si el retorno es menor que el stake, la casa gana la diferencia. Si es mayor, la casa asume el costo.
            diferencia_casa = self.stake - retorno_cashout
            if diferencia_casa > 0:
                LedgerEntry.objects.create(
                    user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=diferencia_casa, direction=EntryDirections.CREDIT
                )
            elif diferencia_casa < 0:
                LedgerEntry.objects.create(
                    user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=abs(diferencia_casa), direction=EntryDirections.DEBIT
                )

            return retorno_cashout
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Ticket #{self.id} | {self.bet_type} | {self.status}"

    @classmethod
    def registrar_apuesta(cls, user, selection_items, stake: Decimal, bet_type: BetType, idempotency_key: str = None):
        if stake < cls.LIMIT_MIN_STAKE or stake > cls.LIMIT_MAX_STAKE:
            raise ValidationError("Monto fuera de los límites permitidos.")

        if not selection_items:
            raise ValidationError("Debe incluir al menos una selección.")

        if bet_type == BetType.SIMPLE and len(selection_items) > 1:
            raise ValidationError("Una apuesta simple solo permite una selección.")

        with transaction.atomic():
            if idempotency_key and cls.objects.filter(idempotency_key=idempotency_key).exists():
                return cls.objects.get(idempotency_key=idempotency_key)

            User.objects.select_for_update().get(id=user.id)

            try:
                profile = user.profile
            except PlayerProfile.DoesNotExist:
                raise ValidationError("Usuario sin perfil KYC.")

            if profile.status != AccountStatus.VERIFIED:
                raise ValidationError("Cuenta no verificada.")

            event_ids = [item['selection'].market.event.id for item in selection_items]
            if len(event_ids) != len(set(event_ids)):
                raise ValidationError("No se permiten múltiples selecciones del mismo partido.")

            total_odds = Decimal('1.0000')
            for item in selection_items:
                sel = item['selection']
                expected_odds = item['expected_odds']
                
                if sel.odds != expected_odds:
                    raise ValidationError(f"La cuota de {sel.name} cambió de {expected_odds} a {sel.odds}. Reconfirme el boleto.")

                # MODIFICACIÓN: Uso de la propiedad perezosa y habilitación de estado LIVE
                if not sel.market.is_betting_allowed:
                    raise ValidationError("Mercado suspendido temporalmente por incidente en vivo o cerrado.")
                
                if sel.market.event.status not in [EventStatus.SCHEDULED, EventStatus.LIVE]:
                    raise ValidationError("El evento ya finalizó o no está disponible.")
                
                total_odds *= sel.odds

            saldo_disponible = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=user)
            if saldo_disponible < stake:
                raise ValidationError("Fondos insuficientes.")

            tx_id = uuid.uuid4()
            LedgerEntry.objects.create(user=user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=stake, direction=EntryDirections.DEBIT)
            LedgerEntry.objects.create(user=user, transaction_id=tx_id, account=WalletAccountTypes.PENDING_BETS, amount=stake, direction=EntryDirections.CREDIT)

            bet = cls.objects.create(
                user=user, stake=stake, odds=total_odds, status=BetStatus.ACCEPTED, bet_type=bet_type, transaction_id=tx_id, idempotency_key=idempotency_key
            )

            for item in selection_items:
                BetSelection.objects.create(bet=bet, selection=item['selection'], odds=item['selection'].odds)

            return bet

    def liquidar_ticket(self):
        if self.status != BetStatus.ACCEPTED:
            raise ValidationError("Ticket ya liquidado.")

        with transaction.atomic():
            tx_id = uuid.uuid4()
            selections_rel = self.bet_selections.all()

            alguna_perdida = any(bs.selection.result == SelectionResult.LOST for bs in selections_rel)
            todas_anuladas = all(bs.selection.result == SelectionResult.VOID for bs in selections_rel)

            LedgerEntry.objects.create(user=self.user, transaction_id=tx_id, account=WalletAccountTypes.PENDING_BETS, amount=self.stake, direction=EntryDirections.DEBIT)

            if todas_anuladas:
                self.status = BetStatus.CANCELED
                LedgerEntry.objects.create(user=self.user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=self.stake, direction=EntryDirections.CREDIT)
            elif alguna_perdida:
                self.status = BetStatus.LOST
                LedgerEntry.objects.create(user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=self.stake, direction=EntryDirections.CREDIT)
            else:
                cuota_efectiva = Decimal('1.0000')
                for bs in selections_rel:
                    if bs.selection.result == SelectionResult.WON:
                        cuota_efectiva *= bs.odds

                self.status = BetStatus.WON
                payout_total = self.stake * cuota_efectiva
                costo_casa = payout_total - self.stake

                if costo_casa > 0:
                    LedgerEntry.objects.create(user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=costo_casa, direction=EntryDirections.DEBIT)
                LedgerEntry.objects.create(user=self.user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=payout_total, direction=EntryDirections.CREDIT)

            self.save()

class BetSelection(models.Model):
    bet = models.ForeignKey(Bet, on_delete=models.CASCADE, related_name='bet_selections')
    selection = models.ForeignKey(Selection, on_delete=models.CASCADE, related_name='bet_selections')
    odds = models.DecimalField(max_digits=18, decimal_places=4)