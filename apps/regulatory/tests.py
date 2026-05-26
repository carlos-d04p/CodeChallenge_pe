from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from apps.accounts.models import PlayerProfile, AccountStatus
from apps.regulatory.models import PlayerPlayLimits, AutoExclusionRecord

class ResponsibleGamingTestCase(TestCase):
    def setUp(self):
        """Estructura el ambiente de control de jugadores."""
        self.user = User.objects.create_user(username="carlos_responsable", password="securepassword")
        self.profile = PlayerProfile.objects.create(
            user=self.user,
            dni="72618751",           # <- Cambiado por un DNI válido
            verification_digit="2",   # <- Dígito verificador matemático correcto
            birth_date=timezone.now().date() - timezone.timedelta(days=365 * 30),
            status=AccountStatus.VERIFIED
        )
        self.limits = PlayerPlayLimits.objects.create(user=self.user)

    def test_reduccion_instantanea_de_limite(self):
        """Prueba que bajar el límite se aplique de inmediato sin trabas ni esperas."""
        self.limits.solicitar_cambio_limite_diario(Decimal('500.0000'))
        self.assertEqual(self.limits.daily_deposit_limit, Decimal('500.0000'))
        self.assertFalse(self.limits.pending_daily_limit)

    def test_incremento_con_cooldown_bloqueante(self):
        """Asegura que subir el límite no sea inmediato y exija esperar 24 horas."""
        # Intentamos subir de 1000 a 1500 fichas (Corregido a 1500)
        self.limits.solicitar_cambio_limite_diario(Decimal('1500.0000')) 
        
        # El límite oficial debe seguir congelado en el valor original
        self.limits.refresh_from_db()
        self.assertNotEqual(self.limits.daily_deposit_limit, Decimal('1500.0000'))
        
        # La solicitud pendiente ahora sí será 1500 (Corregido a 1500)
        self.assertEqual(self.limits.pending_daily_limit, Decimal('1500.0000'))

        # Intentar consolidarlo inmediatamente debe disparar una ValidationError
        with self.assertRaises(ValidationError):
            self.limits.consolidar_incremento_pendiente()

    def test_autoexclusion_bloquea_reversion_temprana(self):
        """Valida que el usuario no pueda sabotear su autoexclusión antes de tiempo."""
        # Nos autoexcluimos por 30 días
        AutoExclusionRecord.registrar_autoexclusion(self.user, dias_duracion=30)
        self.assertEqual(self.user.profile.status, AccountStatus.SELF_EXCLUDED)

        # Intentar forzar la reactivación de la cuenta debe fallar rotundamente
        with self.assertRaises(ValidationError):
            AutoExclusionRecord.intentar_revertir_autoexclusion(self.user)


    def test_cambio_limite_redundante_bloqueado(self):
        """Valida que solicitar el mismo límite actual arroje un error defensivo."""
        # El límite por defecto al crear la cuenta es 1000.0000
        limite_actual = self.limits.daily_deposit_limit
        
        with self.assertRaises(ValidationError) as context:
            self.limits.solicitar_cambio_limite_diario(limite_actual)
            
        # Verificamos que el mensaje de error sea exactamente el que programamos
        self.assertIn("idéntico al actual", str(context.exception))
        
        # Confirmamos que las variables de cooldown siguen limpias
        self.assertIsNone(self.limits.pending_daily_limit)
        self.assertIsNone(self.limits.cooldown_until)