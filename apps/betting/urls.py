from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.betting.views import BetViewSet

router = DefaultRouter()
router.register(r'bets', BetViewSet, basename='bet')

urlpatterns = [
    path('', include(router.urls)),
]