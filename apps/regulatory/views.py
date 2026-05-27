from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from rest_framework import status
from apps.regulatory.models import ImmutableLog

class AuditVerificationView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        es_valido, errores = ImmutableLog.verificar_integridad()
        if es_valido:
            return Response({
                "status": "SUCCESS",
                "message": "La integridad de la cadena está intacta. No se detectaron alteraciones."
            }, status=status.HTTP_200_OK)
            
        return Response({
            "status": "CORRUPTED",
            "message": "Se detectaron alteraciones en la base de datos de auditoría.",
            "errors": errores
        }, status=status.HTTP_400_BAD_REQUEST)
