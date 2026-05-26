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