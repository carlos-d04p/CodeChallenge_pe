from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from decimal import Decimal
from apps.wallet.models import LedgerEntry, WalletAccountTypes, EntryDirections

class WalletOperationsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carlos_tester", password="password123")

    def test_operacion_recarga_exito_y_partida_doble(self):
        """Prueba que la recarga aumente el saldo y cree movimientos balanceados que sumen cero."""
        monto_recarga = Decimal("500.0000")
        tx_id = LedgerEntry.registrar_recarga(self.user, monto_recarga)

        # 1. Comprobar saldo derivado del usuario
        saldo_usuario = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user)
        self.assertEqual(saldo_usuario, monto_recarga)

        # 2. Comprobar partida doble: Suma de créditos menos débitos de la transacción debe ser cero
        entradas_tx = LedgerEntry.objects.filter(transaction_id=tx_id)
        creditos = entradas_tx.filter(direction=EntryDirections.CREDIT).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        debitos = entradas_tx.filter(direction=EntryDirections.DEBIT).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        self.assertEqual(creditos - debitos, Decimal("0.0000"))

    def test_operacion_retiro_exito_y_insuficiencia(self):
        """Prueba que los retiros descuenten saldo y impidan quedar en saldo negativo."""
        # Primero recargamos 100
        LedgerEntry.registrar_recarga(self.user, Decimal("100.0000"))
        
        # Retiramos 40 de forma exitosa
        LedgerEntry.registrar_retiro(self.user, Decimal("40.0000"))
        saldo_luego_retiro = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user)
        self.assertEqual(saldo_luego_retiro, Decimal("60.0000"))

        # Intentar retirar más de lo que se tiene debe lanzar ValidationError (Invariante no negativo)
        with self.assertRaises(ValidationError):
            LedgerEntry.registrar_retiro(self.user, Decimal("200.0000"))

    def test_transferencia_interna_apuestas_pendientes(self):
        """Prueba la transferencia hacia la cuenta de apuestas pendientes."""
        LedgerEntry.registrar_recarga(self.user, Decimal("100.0000"))
        
        # Transferimos 30 fichas a la cuenta de apuestas pendientes (Simulando una apuesta colocada)
        LedgerEntry.registrar_transferencia_interna(
            user=self.user, 
            cuenta_destino=WalletAccountTypes.PENDING_BETS, 
            monto=Decimal("30.0000")
        )

        saldo_disponible = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user)
        saldo_congelado = LedgerEntry.get_balance(WalletAccountTypes.PENDING_BETS, user=self.user)

        self.assertEqual(saldo_disponible, Decimal("70.0000"))
        self.assertEqual(saldo_congelado, Decimal("30.0000"))