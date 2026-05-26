from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
import uuid

from apps.accounts.models import PlayerProfile, AccountStatus
# CORREGIDO: Eliminamos SelectionType de la importación
from apps.events.models import Event, EventStatus, Market, MarketStatus, Selection, SelectionResult
from apps.wallet.models import LedgerEntry, WalletAccountTypes
from apps.betting.models import Bet, BetStatus

class AdvancedBetEngineTestCase(TestCase):
    def setUp(self):
        """Configuración del ambiente real de simulación."""
        self.user = User.objects.create_user(username="carlos_pro_player", password="password123")
        self.profile = PlayerProfile.objects.create(
            user=self.user,
            dni="44556622",
            verification_digit="1",
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 25),
            status=AccountStatus.VERIFIED
        )
        
        # Cargar saldo inicial
        LedgerEntry.registrar_recarga(self.user, Decimal("200.0000"))

        # Configurar catálogo deportivo
        self.event = Event.objects.create(
            title="Gran Final del Mundial",
            home_team="Perú",
            away_team="Argentina",
            kick_off=timezone.now() + timezone.timedelta(days=1),
            status=EventStatus.SCHEDULED
        )
        self.market = Market.objects.create(event=self.event, name="Resultado Final (1X2)", code="1X2")
        self.selection_home = Selection.objects.create(market=self.market, name="Gana Local", odds=Decimal("3.0000"))

    def test_colocar_apuesta_exito_y_congelamiento(self):
        """Prueba que el flujo base congele fondos y cree el ticket correctamente."""
        bet = Bet.procesar_apuesta_simple(self.user, self.selection_home, Decimal("50.0000"))
        self.assertEqual(bet.status, BetStatus.ACCEPTED)
        
        # Comprobar balance derivado
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user), Decimal("150.0000"))
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.PENDING_BETS, user=self.user), Decimal("50.0000"))

    def test_mejora_idempotencia_ticket_duplicado(self):
        """Asegura que dos solicitudes idénticas no descuenten saldo doblemente."""
        key_unica = "request_uuid_12345"
        
        bet_primera = Bet.procesar_apuesta_simple(self.user, self.selection_home, Decimal("20.0000"), idempotency_key=key_unica)
        bet_segunda = Bet.procesar_apuesta_simple(self.user, self.selection_home, Decimal("20.0000"), idempotency_key=key_unica)
        
        # Deben ser exactamente la misma instancia sin haber cobrado de más
        self.assertEqual(bet_primera.id, bet_segunda.id)
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user), Decimal("180.0000"))

    def test_mejora_mercado_suspendido_bloquea_apuesta(self):
        """Debe rechazar la jugada si el mercado cambió su estado a suspendido."""
        self.market.status = MarketStatus.SUSPENDED
        self.market.save()

        with self.assertRaises(ValidationError):
            Bet.procesar_apuesta_simple(self.user, self.selection_home, Decimal("10.0000"))

    def test_mejora_liquidacion_anulada_hace_refund(self):
        """Prueba que un partido anulado devuelva las fichas íntegras al usuario."""
        bet = Bet.procesar_apuesta_simple(self.user, self.selection_home, Decimal("100.0000"))
        
        # Se liquida como ANULADO (VOID)
        bet.liquidar_ticket(SelectionResult.VOID)
        
        self.assertEqual(bet.status, BetStatus.CANCELED)
        # El saldo del usuario debe volver a ser 200 y el congelado quedar en 0
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user), Decimal("200.0000"))
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.PENDING_BETS, user=self.user), Decimal("0.0000"))