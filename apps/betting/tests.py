from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from apps.accounts.models import PlayerProfile, AccountStatus
from apps.events.models import Event, EventStatus, Market, Selection, SelectionResult
from apps.wallet.models import LedgerEntry, WalletAccountTypes
from apps.betting.models import Bet, BetStatus, BetType

class CombinedBetEngineTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carlos_acc", password="password123")
        self.profile = PlayerProfile.objects.create(
            user=self.user, 
            dni="72618751",           # <- DNI real matemáticamente válido
            verification_digit="2",   # <- Dígito correcto
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 25),
            status=AccountStatus.VERIFIED
        )
        # Saldo inicial: 300 fichas
        LedgerEntry.registrar_recarga(self.user, Decimal("300.0000"))

        # Evento 1
        self.event1 = Event.objects.create(title="Partido 1", home_team="Perú", away_team="Chile", kick_off=timezone.now() + timezone.timedelta(days=1))
        self.market1 = Market.objects.create(event=self.event1, code="1X2")
        self.sel1 = Selection.objects.create(market=self.market1, name="Gana Local", odds=Decimal("2.0000"))
        self.sel1_away = Selection.objects.create(market=self.market1, name="Gana Visitante", odds=Decimal("3.0000"))

        # Evento 2
        self.event2 = Event.objects.create(title="Partido 2", home_team="Brasil", away_team="Ecuador", kick_off=timezone.now() + timezone.timedelta(days=1))
        self.market2 = Market.objects.create(event=self.event2, code="1X2")
        self.sel2 = Selection.objects.create(market=self.market2, name="Gana Local", odds=Decimal("1.5000"))

    def test_apuesta_combinada_exito_cuota_acumulada(self):
        bet = Bet.registrar_apuesta(self.user, [self.sel1, self.sel2], Decimal("100.0000"), BetType.COMBINED)
        self.assertEqual(bet.status, BetStatus.ACCEPTED)
        self.assertEqual(bet.odds, Decimal("3.0000")) # 2.0 * 1.5

    def test_exclusion_mutua_mismo_evento_falla(self):
        with self.assertRaises(ValidationError):
            Bet.registrar_apuesta(self.user, [self.sel1, self.sel1_away], Decimal("50.0000"), BetType.COMBINED)

    def test_liquidacion_combinada_ganadora(self):
        bet = Bet.registrar_apuesta(self.user, [self.sel1, self.sel2], Decimal("100.0000"), BetType.COMBINED)
        
        self.sel1.result = SelectionResult.WON
        self.sel1.save()
        self.sel2.result = SelectionResult.WON
        self.sel2.save()

        bet.liquidar_ticket()
        self.assertEqual(bet.status, BetStatus.WON)
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user), Decimal("500.0000")) # 200 restante + 300 payout

    def test_liquidacion_combinada_perdedora(self):
        bet = Bet.registrar_apuesta(self.user, [self.sel1, self.sel2], Decimal("100.0000"), BetType.COMBINED)
        
        self.sel1.result = SelectionResult.LOST
        self.sel1.save()

        bet.liquidar_ticket()
        self.assertEqual(bet.status, BetStatus.LOST)
        
    def test_mejora_liquidacion_anulada_hace_refund(self):
        """Prueba que un partido anulado devuelva las fichas íntegras al usuario."""
        # Código actualizado al nuevo motor de apuestas
        bet = Bet.registrar_apuesta(self.user, [self.sel1], Decimal("100.0000"), BetType.SIMPLE)
        
        # Se liquida el partido de forma interna como ANULADO (VOID)
        self.sel1.result = SelectionResult.VOID
        self.sel1.save()
        
        bet.liquidar_ticket()
        
        self.assertEqual(bet.status, BetStatus.CANCELED)
        # Si recargó 300, apostó 100 (le quedaron 200) y se le hizo refund de 100, vuelve a tener 300
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.USER_WALLET, user=self.user), Decimal("300.0000"))
        self.assertEqual(LedgerEntry.get_balance(WalletAccountTypes.PENDING_BETS, user=self.user), Decimal("0.0000"))