from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.events.models import Event, EventStatus, Market, MarketStatus, Selection

class SportsbookCatalogTestCase(TestCase):
    def setUp(self):
        """Configura el escenario inicial para las pruebas del catálogo."""
        self.fecha_partido = timezone.now() + timezone.timedelta(days=2)
        
        # Creamos el evento usando tus campos exclusivos (title, kick_off)
        self.event = Event.objects.create(
            title="Apertura del Mundial 2026",
            home_team="Perú",
            away_team="Alemania",
            kick_off=self.fecha_partido,
            status=EventStatus.SCHEDULED
        )
        
        # Creamos el mercado usando el campo 'code'
        self.market = Market.objects.create(
            event=self.event,
            name="Resultado Final (1X2)",
            code="1X2",
            operator_margin=Decimal('0.0500')
        )

    def test_registro_exclusivo_evento_y_mercado(self):
        """Verifica que los campos personalizados guarden la data correctamente."""
        self.assertEqual(self.event.title, "Apertura del Mundial 2026")
        self.assertEqual(self.market.code, "1X2")
        self.assertEqual(self.market.operator_margin, Decimal('0.0500'))

    def test_maquina_de_estados_del_partido(self):
        """Prueba que el partido respete el flujo lógico de estados."""
        # 1. Transición permitida: programado -> en_vivo
        self.event.cambiar_estado(EventStatus.LIVE)
        self.assertEqual(self.event.status, EventStatus.LIVE)

        # 2. Transición inválida: un partido en_vivo NO puede volver a programado
        with self.assertRaises(ValidationError):
            self.event.cambiar_estado(EventStatus.SCHEDULED)

    def test_validacion_matematica_de_cuotas(self):
        """Asegura que el sistema rechace cuotas comerciales imposibles (<= 1.00)."""
        # Una cuota de 1.8500 es totalmente válida y debe guardarse sin problemas
        seleccion_valida = Selection.objects.create(
            market=self.market,
            name="Gana Local",
            odds=Decimal('1.8500')
        )
        self.assertIsNotNone(seleccion_valida.id)

        # Una cuota de 1.0000 o menor debe ser rechazada por el método clean() del modelo
        seleccion_invalida = Selection(
            market=self.market,
            name="Empate",
            odds=Decimal('1.0000')
        )
        with self.assertRaises(ValidationError):
            seleccion_invalida.save()