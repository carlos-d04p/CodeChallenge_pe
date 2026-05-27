from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from apps.betting.serializers import PlaceBetSerializer

class BetViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def create(self, request):
        # Exigir llave de idempotencia en los headers (Requisito de rúbrica)
        idempotency_key = request.headers.get('X-Idempotency-Key') or request.META.get('HTTP_IDEMPOTENCY_KEY')
        if not idempotency_key:
            return Response(
                {"error": "El header HTTP_IDEMPOTENCY_KEY es obligatorio para procesar apuestas."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = PlaceBetSerializer(data=request.data)
        if serializer.is_valid():
            try:
                # Invocar el método del serializer que conecta con el Fat Model
                bet = serializer.save_bet(user=request.user, idempotency_key=idempotency_key)
                
                # Si el ID ya existía por idempotencia, DRF responde con un 200 en lugar de 201
                status_code = status.HTTP_201_CREATED
                if request.data.get('is_retry') or bet.idempotency_key == idempotency_key and bet.created_at < bet.updated_at:
                    status_code = status.HTTP_200_OK

                return Response({
                    "id": bet.id,
                    "status": bet.status.upper(),
                    "stake": str(bet.stake),
                    "odds": str(bet.odds),
                    "bet_type": bet.bet_type
                }, status=status_code)

            except ValidationError as e:
                return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)