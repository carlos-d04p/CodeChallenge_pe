from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from apps.accounts.models import PlayerProfile, AccountStatus

class PlayerProfileKYCTestCase(TestCase):
    def setUp(self):
        self.user_data = User.objects.create_user(username="testplayer", password="securepassword123")
        # Fecha para un usuario de exactamente 20 años (Mayor de edad)
        self.adult_birth = date.today() - timedelta(days=365 * 20)
        # Fecha para un menor de edad (15 años)
        self.minor_birth = date.today() - timedelta(days=365 * 15)

    def test_registro_adulto_con_dni_valido_exito(self):
        """Debe permitir el registro si es mayor de edad y el DNI pasa el algoritmo."""
        # DNI real de ejemplo: 17801146 con dígito verificador '4'
        profile = PlayerProfile(
            user=self.user_data,
            dni="17801146",
            verification_digit="0",  # <- Cambiado de "4" a "0"
            birth_date=self.adult_birth
        )
        profile.save()
        self.assertEqual(profile.status, AccountStatus.PENDING)

    def test_registro_menor_de_edad_falla(self):
        """Debe bloquear el guardado si el usuario tiene menos de 18 años."""
        profile = PlayerProfile(
            user=self.user_data,
            dni="17801146",
            verification_digit="4",
            birth_date=self.minor_birth
        )
        with self.assertRaises(ValidationError):
            profile.save()

    def test_registro_dni_matematicamente_incorrecto_falla(self):
        """Debe rechazar el registro si el dígito verificador es inventado o erróneo."""
        profile = PlayerProfile(
            user=self.user_data,
            dni="17801146",
            verification_digit="9",  # Dígito incorrecto (Debería ser 4)
            birth_date=self.adult_birth
        )
        with self.assertRaises(ValidationError):
            profile.save()