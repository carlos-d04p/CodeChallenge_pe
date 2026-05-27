from rest_framework import serializers
from decimal import Decimal
from apps.betting.models import Bet, BetType
from apps.events.models import Selection

class SelectionItemSerializer(serializers.Serializer):
    selection_id = serializers.IntegerField()
    expected_odds = serializers.DecimalField(max_digits=18, decimal_places=4)

class PlaceBetSerializer(serializers.Serializer):
    stake = serializers.DecimalField(max_digits=18, decimal_places=4)
    bet_type = serializers.ChoiceField(choices=BetType.choices)
    selection_items = SelectionItemSerializer(many=True)

    def validate_stake(self, value):
        if value < Decimal('1.0000'):
            raise serializers.ValidationError("El monto mínimo de apuesta es 1 ficha.")
        return value

    def save_bet(self, user, idempotency_key=None):
        validated_data = self.validated_data
        
        # Mapeo de IDs de la API a objetos reales de la Base de Datos
        items_procesados = []
        for item in validated_data['selection_items']:
            try:
                selection = Selection.objects.get(id=item['selection_id'])
            except Selection.DoesNotExist:
                raise serializers.ValidationError(f"La selección con ID {item['selection_id']} no existe.")
            
            items_procesados.append({
                'selection': selection,
                'expected_odds': item['expected_odds']
            })

        # Invocar tu Fat Model blindado
        return Bet.registrar_apuesta(
            user=user,
            selection_items=items_procesados,
            stake=validated_data['stake'],
            bet_type=validated_data['bet_type'],
            idempotency_key=idempotency_key
        )