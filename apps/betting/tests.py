from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from apps.accounts.models import PlayerProfile, AccountStatus
# CORRECCIÓN: EventStatus y MarketStatus vienen de events
from apps.events.models import Event, EventStatus, Market, MarketStatus, Selection
from apps.wallet.models import LedgerEntry, WalletAccountTypes
# CORRECCIÓN: BetStatus viene de betting
from apps.betting.models import Bet, BetType, BetStatus

class RequotationPolicyTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carlos_live", password="password123")
        self.profile = PlayerProfile.objects.create(
            user=self.user, 
            dni="72618751",           
            verification_digit="2",   
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 25),
            status=AccountStatus.VERIFIED
        )
        LedgerEntry.registrar_recarga(self.user, Decimal("200.0000"))

        self.event = Event.objects.create(title="Live Match", home_team="Francia", away_team="Italia", kick_off=timezone.now() + timezone.timedelta(days=1))
        self.market = Market.objects.create(event=self.event, code="1X2")
        self.sel = Selection.objects.create(market=self.market, name="Gana Local", odds=Decimal("2.0000"))

    def test_apuesta_rechazada_si_cuota_cambia(self):
        items = [{'selection': self.sel, 'expected_odds': Decimal('1.9000')}]
        
        with self.assertRaises(ValidationError):
            Bet.registrar_apuesta(self.user, items, Decimal("50.0000"), BetType.SIMPLE)

    def test_apuesta_exitosa_si_cuota_coincide(self):
        items = [{'selection': self.sel, 'expected_odds': Decimal('2.0000')}]
        bet = Bet.registrar_apuesta(self.user, items, Decimal("50.0000"), BetType.SIMPLE)
        self.assertIsNotNone(bet.id)
    
class InPlayBettingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carlos_inplay", password="password123")
        self.profile = PlayerProfile.objects.create(
            user=self.user, 
            dni="17801146",           # <- DNI real matemáticamente válido
            verification_digit="0",   # <- Dígito correcto
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 25),
            status=AccountStatus.VERIFIED
        )
        LedgerEntry.registrar_recarga(self.user, Decimal("200.0000"))

        self.event = Event.objects.create(title="Partido en Vivo", home_team="Real Madrid", away_team="Barcelona", kick_off=timezone.now() - timezone.timedelta(minutes=30), status=EventStatus.LIVE)
        self.market = Market.objects.create(event=self.event, code="1X2")
        self.sel = Selection.objects.create(market=self.market, name="Gana Local", odds=Decimal("2.5000"))

    def test_apuesta_permitida_en_partido_live(self):
        items = [{'selection': self.sel, 'expected_odds': Decimal('2.5000')}]
        bet = Bet.registrar_apuesta(self.user, items, Decimal("50.0000"), BetType.SIMPLE)
        self.assertEqual(bet.status, BetStatus.ACCEPTED)

    def test_suspension_por_gol_bloquea_apuesta(self):
        self.market.suspender_por_incidente(segundos=15)
        
        items = [{'selection': self.sel, 'expected_odds': Decimal('2.5000')}]
        with self.assertRaises(ValidationError):
            Bet.registrar_apuesta(self.user, items, Decimal("50.0000"), BetType.SIMPLE)

    def test_mercado_se_reabre_automaticamente_tras_tiempo(self):
        self.market.suspender_por_incidente(segundos=-5)
        
        items = [{'selection': self.sel, 'expected_odds': Decimal('2.5000')}]
        bet = Bet.registrar_apuesta(self.user, items, Decimal("50.0000"), BetType.SIMPLE)
        
        self.assertEqual(bet.status, BetStatus.ACCEPTED)
        self.market.refresh_from_db()
        self.assertEqual(self.market.status, MarketStatus.OPEN)

    
class CashoutBettingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carlos_cashout", password="password123")
        self.profile = PlayerProfile.objects.create(
            user=self.user, 
            dni="77889911",           
            verification_digit="5",
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 25),
            status=AccountStatus.VERIFIED
        )
        LedgerEntry.registrar_recarga(self.user, Decimal("100.0000"))

        self.event = Event.objects.create(title="Match Cashout", home_team="Arsenal", away_team="Chelsea", kick_off=timezone.now() + timezone.timedelta(days=1))
        self.market = Market.objects.create(event=self.event, code="1X2")
        self.sel = Selection.objects.create(market=self.market, name="Gana Local", odds=Decimal("2.0000"))

        # El usuario coloca una apuesta inicial de 10 fichas a cuota 2.0
        items = [{'selection': self.sel, 'expected_odds': Decimal('2.0000')}]
        self.bet = Bet.registrar_apuesta(self.user, items, Decimal("10.0000"), BetType.SIMPLE)

    def test_ejecutar_cashout_exito_y_balanceo_contable(self):
        """
        Fórmula: 10 * 2.0 / 1.5 * 0.95 = 12.6667 (Retorno aproximado a 4 decimales)
        Saldo inicial tras apostar: 90.0000
        Saldo final esperado: 90.0000 + 12.6667 = 102.6667
        """
        odds_actual = Decimal("1.5000")
        factor_casa = Decimal("0.9500")

        retorno = self.bet.ejecutar_cashout(odds_actual, factor_casa)
        
        self.assertEqual(retorno, Decimal("12.6667"))
        self.assertEqual(self.bet.status, BetStatus.CANCELED)

        # Verificar saldos en billetera
        saldo_usuario = LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user)
        saldo_pendientes = LedgerEntry.get_balance(WalletAccountTypes.PENDING_BETS, user=self.user)
        
        self.assertEqual(saldo_usuario, Decimal("102.6667"))
        self.assertEqual(saldo_pendientes, Decimal("0.0000"))

    def test_bloqueo_cashout_apuesta_ya_cancelada(self):
        self.bet.ejecutar_cashout(Decimal("1.5000"))
        
        # Intentar de nuevo sobre el mismo ticket debe fallar
        with self.assertRaises(ValidationError):
            self.bet.ejecutar_cashout(Decimal("1.5000"))