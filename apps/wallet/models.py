from django.db import models, transaction
from django.db.models import Sum
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid

class WalletAccountTypes(models.TextChoices):
    USER_WALLET = 'wallet_usuario', 'Billetera de Usuario'
    SYSTEM_HOUSE = 'casa', 'Cuenta de la Casa'
    PENDING_BETS = 'apuestas_pendientes', 'Apuestas Pendientes'
    BONUS = 'bonos', 'Cuenta de Bonos'

class EntryDirections(models.TextChoices):
    DEBIT = 'DEBIT', 'Débito (Salida)'
    CREDIT = 'CREDIT', 'Crédito (Entrada)'

class LedgerEntry(models.Model):
    # Enlace opcional al usuario (la cuenta de la casa no tiene usuario asociado)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='ledger_entries')
    transaction_id = models.UUIDField(help_text="UUID que amarra los movimientos de una misma operación.")
    account = models.CharField(max_length=25, choices=WalletAccountTypes.choices)
    
    # Precisión exacta obligatoria: 18 dígitos, 4 decimales. Prohibido floats.
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    direction = models.CharField(max_length=6, choices=EntryDirections.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Entrada de Libro Contable"
        verbose_name_plural = "Entradas de Libro Contable"

    def __str__(self):
        return f"{self.transaction_id} | {self.account} | {self.direction} | {self.amount}"

    @classmethod
    def get_balance(cls, account_name, user=None):
        """
        Calcula el saldo dinámicamente: SUM(credits) - SUM(debits). Nunca se guarda.
        """
        queryset = cls.objects.filter(account=account_name)
        if user:
            queryset = queryset.filter(user=user)
            
        credits = queryset.filter(direction=EntryDirections.CREDIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.0000')
        debits = queryset.filter(direction=EntryDirections.DEBIT).aggregate(total=Sum('amount'))['total'] or Decimal('0.0000')
        
        return credits - debits
    
    @classmethod
    def registrar_recarga(cls, user, monto: Decimal):
        """Operación 1: Recarga simulada de fichas."""
        if monto <= 0:
            raise ValidationError("El monto de la recarga debe ser mayor a cero.")
            
        tx_id = uuid.uuid4()
        with transaction.atomic():
            # Bloqueo pesimista del usuario para evitar condiciones de carrera (concurrencia)
            User.objects.select_for_update().get(id=user.id)
            
            # Entrada: Crédito a la billetera del usuario
            cls.objects.create(user=user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=monto, direction=EntryDirections.CREDIT)
            # Salida: Débito a la cuenta de la casa (La casa provee las fichas de juguete)
            cls.objects.create(user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=monto, direction=EntryDirections.DEBIT)
        return tx_id

    @classmethod
    def registrar_retiro(cls, user, monto: Decimal):
        """Operación 2: Retiro simulado de fichas."""
        if monto <= 0:
            raise ValidationError("El monto del retiro debe ser mayor a cero.")
            
        tx_id = uuid.uuid4()
        with transaction.atomic():
            # Bloqueo pesimista del usuario
            User.objects.select_for_update().get(id=user.id)
            
            # Validar invariante: Ningún wallet termina con saldo negativo
            saldo_actual = cls.get_balance(WalletAccountTypes.USER_WALLET, user=user)
            if saldo_actual < monto:
                raise ValidationError("Saldo insuficiente para efectuar el retiro simulado.")
                
            # Salida: Débito a la billetera del usuario
            cls.objects.create(user=user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=monto, direction=EntryDirections.DEBIT)
            # Entrada: Crédito a la cuenta de la casa
            cls.objects.create(user=None, transaction_id=tx_id, account=WalletAccountTypes.SYSTEM_HOUSE, amount=monto, direction=EntryDirections.CREDIT)
        return tx_id

    @classmethod
    def registrar_transferencia_interna(cls, user, cuenta_destino, monto: Decimal):
        """Operación 3: Transferencia interna (Útil para congelar fondos al apostar)."""
        if monto <= 0:
            raise ValidationError("El monto de la transferencia debe ser mayor a cero.")
            
        tx_id = uuid.uuid4()
        with transaction.atomic():
            User.objects.select_for_update().get(id=user.id)
            
            saldo_actual = cls.get_balance(WalletAccountTypes.USER_WALLET, user=user)
            if saldo_actual < monto:
                raise ValidationError("Saldo insuficiente para realizar la transferencia interna.")
                
            # Salida: Débito de la billetera del usuario
            cls.objects.create(user=user, transaction_id=tx_id, account=WalletAccountTypes.USER_WALLET, amount=monto, direction=EntryDirections.DEBIT)
            # Entrada: Crédito a la cuenta de destino del sistema (ej: apuestas_pendientes)
            cls.objects.create(user=user, transaction_id=tx_id, account=cuenta_destino, amount=monto, direction=EntryDirections.CREDIT)
        return tx_id