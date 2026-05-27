from django.urls import path
from apps.regulatory.views import AuditVerificationView

urlpatterns = [
    path('audit/verify/', AuditVerificationView.as_view(), name='audit-verify'),
]